#!/home/svdleer/python/venv/bin/python
 
###########################################################################################################
#
# fixofdm.py 
#
# Description : Script to remove impaired OFDM downstream channel from modem RCP to prevent issues
# Platform    : Commscope E6000
# Created on  : 08-12-2025
# Autor       : Silvester van der Leer
# Company     : VodafoneZiggo
# Version     : 0.1
#
# GPL version 2 is valid 
#
# Notes : this script is far from perfect and will be improved on the way
#
###########################################################################################################


import re
import logging
import mysql.connector
import threading
import time
from netmiko import ConnectHandler
from cryptography.fernet import Fernet
from concurrent.futures import ThreadPoolExecutor, as_completed
from mysql.connector import pooling


netmiko_logger = logging.getLogger("netmiko")
netmiko_logger.setLevel(logging.WARNING)

def create_mysql_pool():
    pool = pooling.MySQLConnectionPool(
        pool_name="ofdmpool",
        pool_size=20,  
        pool_reset_session=True,  
        host='appdb.oss.local',
        database='access',
        user='access',
        password='44cC3sS'
    )
    return pool


def mysql_insert(cnx, cmts, cablemac, interface, impairedchan, mac, impairment_count, all_impaired_channels, original_rcs):
    add_data = ("REPLACE INTO ofdmpartial (cmts, cablemac, interface, impairedchan, mac, impairment_count, all_impaired_channels, original_rcs) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)")
    data = (cmts, cablemac, interface, impairedchan, mac, impairment_count, all_impaired_channels, original_rcs)
    print(f"DEBUG: Inserting to DB: {data}")
    try:
        cursor = cnx.cursor()
        cursor.execute(add_data, data)
        cnx.commit()
    except mysql.connector.Error as err:
        print(f"Failed to insert data: {err}")


def get_devices(pool):
    get_cmts_db = "SELECT UPPER(ccap) from ofdmpartial_ccaps WHERE active='1' AND ccap LIKE '%bd-rc0002-ccap002'"
    try:
        cnx = pool.get_connection()
        cursor = cnx.cursor()
        cursor.execute(get_cmts_db)
        rows = cursor.fetchall()
        data = [item[0] for item in rows]
        return(data)

    except mysql.connector.Error as err:
        print(f"Failed to select data: {err}")

def connect_to_cmts(host, username, password):
    cmts = {
        'device_type': 'cisco_ios', 
        'host': host,
        'username': username,
        'password': password,
        'global_delay_factor': 1,
    }

    try:
        cmts_connect = ConnectHandler(**cmts, fast_cli=True,  use_keys=False)
        print(f"Thread ID: {threading.get_ident()} - Connected to {cmts['host']}")
        return cmts_connect
    except Exception as e:
        print("An error occurred while connecting:", str(e))
        return None

def send_command(cmts_connect, command):
    try:
        output = cmts_connect.send_command(command, read_timeout=120)
        return output
    except Exception as e:
        print("An error occurred while sending command:", str(e))
        return None


def write_mem(cmts_connect):
    try:
       write_mem_output = send_command(cmts_connect, 'write memory')
       if write_mem_output:
          print('Configuration saved')
    except Exception as e:
        print("An error occurred:", str(e))
        return None


def check_ds_bonding_group(cmts_connect, cablemac, bg):
    command_output = send_command(cmts_connect, 'show running-config interface cable-mac '+cablemac +' verbose | include downstream-bonding-group '+bg+' | include cable-downstream')
    if command_output:
        for line in command_output.split('\n'):
            if 'configure' in line:
                return line
    return None

def get_cm_lb_group(cmts_connect, cmmac):
    try:
        get_lb_group_cmd = send_command(cmts_connect, 'show cable modem '+cmmac+ ' detail | include "LB Group"')
        if get_lb_group_cmd:
            for line in get_lb_group_cmd.split('\n'):
                if line.strip():
                    if 'LB' in line:
                        match = re.search(r'LB Group=(\d+)', line)
                        if match:
                            lb_group_value = int(match.group(1))
                            return(str(lb_group_value))
                        else:
                            print('No LB group found')
                            return None
    except Exception as e:
        print("An error occurred while sending command:", str(e))
        return None


def get_cm_mdssg(cmts_connect, cmmac):
    """Get multicast downstream service group (mDSsg) for the modem"""
    try:
        get_cm_mdssg_cmd = send_command(cmts_connect, 'show cable modem '+cmmac+ ' detail | include "mDSsg"')
        if get_cm_mdssg_cmd:
            for line in get_cm_mdssg_cmd.split('\n'):
                if line.strip():
                    if 'mDSsg' in line:
                        match = re.search(r'mDSsg = (\d+)', line)
                        if match:
                            mdssg_value = int(match.group(1))
                            return(str(mdssg_value))
                        else:
                            print('No mDSsg found')
                            return None
    except Exception as e:
        print("An error occurred while sending command:", str(e))
        return None


def get_current_bonding_group_channels(cmts_connect, cablemac, cm_mdssg):
    """
    Get the channels from the current bonding group that the modem is using.
    Since we're using dynamic bonding groups ({cablemac}1-20), just return None
    to always use RCS channels as the source of truth.
    """
    print(f"DEBUG: Using RCS channels as source (bonding groups are {cablemac}1-20 format)")
    return None


def get_channels_from_rcs(cmts_connect, cablemac, rcs_id):
    """Extract channel list from a specific RCS"""
    try:
        get_cm_channel_set_cmd = send_command(cmts_connect, f'show cable channel-sets cable-mac {cablemac} ds')
        
        if get_cm_channel_set_cmd:
            lines = get_cm_channel_set_cmd.split('\n')
            current_line_channels = []
            found_rcs = False
            
            print(f"DEBUG: Searching for RCS {rcs_id} in cable-mac {cablemac} output ({len(lines)} lines)")
            
            for line in lines:
                line_stripped = line.strip()
                
                if not line_stripped:
                    continue
                
                # Check if this line starts with our cable-mac number
                if line_stripped.startswith(cablemac):
                    fields = line_stripped.split()
                    
                    # Debug: show what RCS IDs we're seeing
                    if len(fields) > 1:
                        print(f"DEBUG: Found cable-mac line with RCS {fields[1]} (looking for {rcs_id})")
                    
                    # If we already found our RCS and now see another cable-mac line, stop
                    if found_rcs:
                        print(f"DEBUG: Stopping - found next RCS entry")
                        break
                    
                    # Check if this is our RCS
                    if len(fields) > 1 and fields[1] == rcs_id:
                        found_rcs = True
                        # Get channels after 'DS' marker
                        if 'DS' in fields:
                            ds_index = fields.index('DS')
                            current_line_channels = fields[ds_index+1:]
                            print(f"DEBUG: Found RCS {rcs_id}, initial channels: {len(current_line_channels)}")
                        else:
                            print(f"DEBUG: Found RCS {rcs_id} but no 'DS' marker in line")
                
                # If we found our RCS, this is a continuation line (doesn't start with cable-mac)
                elif found_rcs:
                    # All lines between this RCS and the next cable-mac line belong to this RCS
                    continuation_channels = line_stripped.split()
                    current_line_channels.extend(continuation_channels)
                    print(f"DEBUG: Added continuation ({len(continuation_channels)} channels), total now: {len(current_line_channels)}")
            
            if not found_rcs:
                print(f"DEBUG: RCS {rcs_id} not found in output")
            
            if current_line_channels:
                # Expand to count actual channels
                expanded = expand_channel_ranges(current_line_channels)
                print(f"DEBUG: RCS {rcs_id} has {len(current_line_channels)} range groups ({len(expanded)} total channels)")
                print(f"DEBUG: Range format: {current_line_channels}")
                return current_line_channels
            else:
                print(f"DEBUG: No channels found for RCS {rcs_id}")
        
        return None
    except Exception as e:
        print(f"ERROR: Error getting channels from RCS: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def find_alternate_ds_bonding_group(cmts_connect, cablemac, impaired_channel, cm_lb_group, cm_mdssg, cm_mac):
    """
    Find or suggest creating an alternate downstream bonding group.
    The new group must have the same channels as the current group, minus the impaired channel(s).
    
    Priority:
    1. Find existing group with same channels minus impaired
    2. Suggest creating new group with same channels minus impaired
    
    Args:
        impaired_channel: Can be a single channel or comma-separated list of channels
    
    Returns dict with 'type' and 'config' or 'group_id'
    """
    try:
        # Get channels from modem's current RCS
        modem_output = send_command(cmts_connect, f'show cable modem {cm_mac} verbose | include RCS')
        current_rcs = None
        current_channels = None
        
        if modem_output:
            rcs_match = re.search(r'RCS=(0x[0-9a-fA-F]+)', modem_output)
            if rcs_match:
                current_rcs = rcs_match.group(1)
                print(f"DEBUG: Modem {cm_mac} current RCS: {current_rcs}")
                
                # Get channels from this RCS
                current_channels = get_channels_from_rcs(cmts_connect, cablemac, current_rcs)
        
        if not current_channels:
            print(f"DEBUG: Could not determine current channels (no bonding group or RCS)")
            return None
        
        # Handle multiple impaired channels (comma-separated)
        if ',' in impaired_channel:
            impaired_channels = [ch.strip().replace('D', '') for ch in impaired_channel.split(',')]
        else:
            impaired_channels = [impaired_channel.replace('D', '')]
        
        print(f"DEBUG: Removing {len(impaired_channels)} impaired channel(s): {impaired_channels}")
        
        # Expand current channels to check if impaired channels are present
        expanded_current = expand_channel_ranges(current_channels)
        
        # Check if ALL impaired channels exist in expanded list
        missing_channels = [ch for ch in impaired_channels if ch not in expanded_current]
        if missing_channels:
            print(f"WARNING: Impaired channel(s) {missing_channels} not found in current bonding group")
            print(f"Current channels: {current_channels}")
            print(f"Expanded to: {expanded_current}")
            # Continue anyway, removing only the channels that exist
        
        # Build the target channel list (expanded current minus ALL impaired channels)
        target_channels = [ch for ch in expanded_current if ch not in impaired_channels]
        
        print(f"DEBUG: Current has {len(expanded_current)} channels, target has {len(target_channels)} channels (removed {len(impaired_channels)} impaired)")
        print(f"DEBUG: Target channels: {target_channels}")
        
        # Get all bonding groups for this cable-mac
        show_bonding = send_command(cmts_connect, f'show running-config interface cable-mac {cablemac} verbose | include downstream-bonding-group')
        
        existing_groups = {}
        used_group_ids = set()
        
        if show_bonding:
            # Parse existing bonding groups
            for line in show_bonding.split('\n'):
                if 'configure interface cable-mac' in line and 'downstream-bonding-group' in line:
                    # Extract bonding group ID and channels
                    match = re.search(r'downstream-bonding-group\s+(\S+)\s+cable-downstream\s+(.+)', line)
                    if match:
                        group_id = match.group(1)
                        channels_str = match.group(2).strip()
                        channels = channels_str.split()
                        
                        existing_groups[group_id] = channels
                        used_group_ids.add(group_id)
            
            print(f"DEBUG: Found {len(existing_groups)} existing static DS bonding groups on cable-mac {cablemac}")
            
            # OPTION 1: Find existing group with exact same channels (order doesn't matter)
            target_set = set(target_channels)
            for group_id, channels in existing_groups.items():
                # Expand range notation to individual channels for comparison
                expanded_channels = expand_channel_ranges(channels)
                if set(expanded_channels) == target_set:
                    print(f"DEBUG: Found existing group {group_id} with exact target channels")
                    print(f"DEBUG: Existing group has {len(expanded_channels)} channels, target has {len(target_channels)} channels")
                    return {
                        'type': 'existing',
                        'group_id': group_id,
                        'channels': channels  # Keep original range format
                    }
        
        # OPTION 2: Create new bonding group with next available ID (cablemac1-20)
        new_group_id = None
        for i in range(1, 21):  # Try IDs 1-20
            candidate_id = f"{cablemac}{i}"
            if candidate_id not in used_group_ids:
                new_group_id = candidate_id
                break
        
        if not new_group_id:
            # All 20 slots used - find existing group with same first channel
            print(f"WARNING: All 20 bonding group slots are used on cable-mac {cablemac}")
            print(f"DEBUG: Looking for existing group with same first channel")
            
            # Get the first channel from target list
            if target_channels:
                first_target_channel = target_channels[0]
                print(f"DEBUG: Modem's first channel: {first_target_channel}")
                
                # Check each existing group
                for group_id, channels in existing_groups.items():
                    expanded = expand_channel_ranges(channels)
                    if expanded and expanded[0] == first_target_channel:
                        print(f"DEBUG: Found existing group {group_id} with matching first channel {first_target_channel}")
                        return {
                            'type': 'existing',
                            'group_id': group_id,
                            'channels': channels
                        }
            
            print(f"ERROR: No suitable bonding group found (all 20 used, no matching first channel)")
            return None
        
        # Compress channels into ranges for shorter command
        compressed_channels = compress_channel_ranges(target_channels)
        config = f"configure interface cable-mac {cablemac} cable downstream-bonding-group {new_group_id} cable-downstream {' '.join(compressed_channels)}"
        
        print(f"DEBUG: Need to create new group {new_group_id} with target channels")
        print(f"DEBUG: Compressed from {len(target_channels)} channels to {len(compressed_channels)} ranges")
        return {
            'type': 'create',
            'config': config,
            'group_id': new_group_id,
            'channels': target_channels
        }
        
    except Exception as e:
        print(f"ERROR: Error finding alternate bonding group: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def expand_channel_ranges(range_list):
    """
    Expand range notation to individual channels.
    Example: ['12/scq/0-2,5-7', '12/ofd/0-1'] -> ['12/scq/0', '12/scq/1', '12/scq/2', '12/scq/5', '12/scq/6', '12/scq/7', '12/ofd/0', '12/ofd/1']
    """
    expanded = []
    for item in range_list:
        # Parse: '12/scq/0-2,5-7' -> prefix='12/scq', ranges='0-2,5-7'
        parts = item.rsplit('/', 1)
        if len(parts) == 2:
            prefix = parts[0]
            range_spec = parts[1]
            
            # Split by comma: '0-2,5-7' -> ['0-2', '5-7']
            for range_part in range_spec.split(','):
                if '-' in range_part:
                    # Range: '0-2' -> 0, 1, 2
                    start, end = range_part.split('-', 1)
                    try:
                        for num in range(int(start), int(end) + 1):
                            expanded.append(f"{prefix}/{num}")
                    except ValueError:
                        # Not a valid range, keep as-is
                        expanded.append(item)
                else:
                    # Single number: '5' -> 5
                    try:
                        expanded.append(f"{prefix}/{int(range_part)}")
                    except ValueError:
                        # Not a number, keep as-is
                        expanded.append(item)
        else:
            # Can't parse, keep as-is
            expanded.append(item)
    
    return expanded


def compress_channel_ranges(channels):
    """
    Compress a list of channels into range format with commas for gaps.
    Example: ['12/scq/0', '12/scq/1', '12/scq/3', '12/scq/4'] -> ['12/scq/0-1,3-4']
    """
    if not channels:
        return []
    
    # Group channels by their prefix (e.g., '12/scq', '12/ofd')
    channel_groups = {}
    for ch in channels:
        # Parse channel: '12/scq/5' -> prefix='12/scq', num=5
        parts = ch.rsplit('/', 1)
        if len(parts) == 2:
            prefix = parts[0]
            try:
                num = int(parts[1])
                if prefix not in channel_groups:
                    channel_groups[prefix] = []
                channel_groups[prefix].append(num)
            except ValueError:
                # If not a number, keep as-is
                if 'other' not in channel_groups:
                    channel_groups['other'] = []
                channel_groups['other'].append(ch)
    
    # Build compressed ranges - SCQ channels must come before OFD channels
    compressed = []
    
    # Custom sort: scq before ofd, then alphabetically
    def channel_sort_key(prefix):
        if prefix == 'other':
            return (2, prefix)  # Other last
        elif '/scq' in prefix:
            return (0, prefix)  # SCQ first
        elif '/ofd' in prefix:
            return (1, prefix)  # OFD second
        else:
            return (2, prefix)  # Everything else last
    
    for prefix in sorted(channel_groups.keys(), key=channel_sort_key):
        if prefix == 'other':
            compressed.extend(channel_groups[prefix])
            continue
            
        nums = sorted(channel_groups[prefix])
        
        # Find consecutive ranges
        ranges = []
        start = nums[0]
        end = nums[0]
        
        for i in range(1, len(nums)):
            if nums[i] == end + 1:
                # Consecutive
                end = nums[i]
            else:
                # Gap found, save current range
                if start == end:
                    ranges.append(f"{start}")
                else:
                    ranges.append(f"{start}-{end}")
                start = nums[i]
                end = nums[i]
        
        # Save last range
        if start == end:
            ranges.append(f"{start}")
        else:
            ranges.append(f"{start}-{end}")
        
        # Combine all ranges for this prefix with commas
        compressed.append(f"{prefix}/{','.join(ranges)}")
    
    return compressed


def add_ds_bonding(cmts_connect, cablemac, bg, ofdmchannel, cmlbgroup):
    """Add downstream bonding group configuration to cable-mac"""
    ds_list = []
    ofdmchannel = ofdmchannel.replace('D', '')
    
    # Parse OFDM channel format: "12/ofd/1" or "12/0/40"
    channel_parts = ofdmchannel.split('/')
    cable_intf = channel_parts[0]
    
    # Detect channel type (old format with /ofd/ or new format with numeric)
    has_ofd = '/ofd/' in ofdmchannel
    
    # Get OFDM downstream interface details
    get_ofdm_interface = send_command(cmts_connect, f'show interface cable-mac {cablemac}')
    
    if get_ofdm_interface:
        for line in get_ofdm_interface.split('\n'):
            fields = line.split()
            if line.strip() and fields:
                # CCCAP format: interface name contains '/ofd/' (e.g., 12/ofd/1)
                # ICCAP format: interface name ends with /40 or /41 (e.g., 12/0/40, 12/0/41)
                interface_name = fields[0] if fields else ''
                is_ofdm_cccap = '/ofd/' in interface_name
                is_ofdm_iccap = interface_name.endswith('/40') or interface_name.endswith('/41')
                
                if is_ofdm_iccap or is_ofdm_cccap:
                    ofdm_interface = fields[0]
                
                # Get SCQ downstream channels for this load balancing group
                get_ds_interface = send_command(cmts_connect, 'show interface cable-mac '+cablemac +' | include '+cable_intf+'/scq | include '+cmlbgroup)
                
                if get_ds_interface:
                    for line2 in get_ds_interface.split('\n'):
                        if 'scq' in line2:
                            ds_interface = line2.split()
                            if len(ds_interface) > 11 and ds_interface[11] == cmlbgroup:
                                # Extract SCQ channel number
                                ds = ds_interface[0].rsplit('/', 1)
                                ds_list.append(ds[1])
                    
                    if ds_list and len(ds_list) >= 4:
                        # Build bonding group command with SCQ range and OFDM channels
                        scq_range = f"{cable_intf}/scq/{ds_list[0]}-{ds_list[-1]}"
                        
                        # Get all OFDM channels except the impaired one
                        ofdm_channels = []
                        for line3 in get_ofdm_interface.split('\n'):
                            if '/ofd/' in line3 and line3.strip():
                                fields3 = line3.split()
                                ofdm_ch = fields3[0]
                                # Skip the impaired channel
                                if ofdmchannel not in ofdm_ch:
                                    # Extract just the channel part (e.g., "12/ofd/0")
                                    ofdm_channels.append(ofdm_ch.split(':')[-1] if ':' in ofdm_ch else ofdm_ch)
                        
                        # Build the complete bonding group command
                        ofdm_part = ' '.join(ofdm_channels) if ofdm_channels else ''
                        add_bonding_group = f'configure interface cable-mac {cablemac} cable downstream-bonding-group {bg}{cablemac} cable-downstream {scq_range} {ofdm_part}'
                        
                        print(f"DEBUG: Would add DS bonding group: {add_bonding_group}")
                        # result = send_command(cmts_connect, add_bonding_group)
                        # return result
                        return None
    return None


def channel_in_range_list(channel, range_list):
    """
    Check if a channel like '12/ofd/1' is in a compressed range list like '12/ofd/0-1' or '12/scq/50-55,57-80'.
    
    Args:
        channel: Full channel string like '12/ofd/1' or '12/scq/55'
        range_list: Space-separated list of ranges like '12/scq/50-81 12/ofd/2-3'
    
    Returns:
        True if channel is in any of the ranges, False otherwise
    """
    # Parse the channel to get prefix and number
    parts = channel.rsplit('/', 1)
    if len(parts) != 2:
        return False
    
    channel_prefix = parts[0]  # e.g., '12/ofd'
    try:
        channel_num = int(parts[1])  # e.g., 1
    except ValueError:
        return False
    
    # Split range_list by spaces to get individual range groups
    for range_group in range_list.split():
        # Check if this range group has the same prefix
        if not range_group.startswith(channel_prefix + '/'):
            continue
        
        # Extract the range part after the prefix
        range_part = range_group[len(channel_prefix) + 1:]  # e.g., '0-1' or '50-55,57-80'
        
        # Split by comma for non-sequential ranges
        for range_segment in range_part.split(','):
            if '-' in range_segment:
                # Range like '0-1' or '50-55'
                start, end = range_segment.split('-', 1)
                try:
                    if int(start) <= channel_num <= int(end):
                        return True
                except ValueError:
                    continue
            else:
                # Single number like '81'
                try:
                    if int(range_segment) == channel_num:
                        return True
                except ValueError:
                    continue
    
    return False


def get_cm_channel_set(cmts_connect, cablemac, impairedchan, cminterface, cm_mac, target_channels=None):
    """
    Get appropriate RCS channel set for modem, excluding the impaired channel(s).
    This is the downstream equivalent of the upstream get_cm_channel_set.
    
    Args:
        impairedchan: Single channel or comma-separated list of impaired channels
        target_channels: List of exact channels the RCS should have (expanded format like ['12/scq/50', '12/scq/51', ...])
    """
    try:
        # Get modem's current RCS
        modem_output = send_command(cmts_connect, f'show cable modem {cm_mac} verbose | include RCS')
        current_rcs = None
        
        if modem_output:
            rcs_match = re.search(r'RCS=(0x[0-9a-fA-F]+)', modem_output)
            if rcs_match:
                current_rcs = rcs_match.group(1)
                print(f"DEBUG: Modem {cm_mac} current RCS: {current_rcs}")
        
        if not current_rcs:
            print(f"Could not find RCS for modem {cm_mac}")
            return None
        
        # Parse impaired channels (could be comma-separated)
        if ',' in impairedchan:
            impaired_list = [ch.strip() for ch in impairedchan.split(',')]
        else:
            impaired_list = [impairedchan]
        
        print(f"DEBUG: Looking for RCS without impaired channel(s): {impaired_list}")
        
        # Get channel sets for this cable-mac
        get_cm_channel_set_cmd = send_command(cmts_connect, 'show cable channel-sets cable-mac '+cablemac+' ds')
        
        if get_cm_channel_set_cmd:
            lines = get_cm_channel_set_cmd.split('\n')
            
            for line in lines:
                channelset = line.split()
                
                # Look for line with a DIFFERENT RCS that doesn't contain ANY impaired channel
                if len(channelset) > 2 and channelset[0] == cablemac:
                    rcs_id = channelset[1]
                    
                    # Skip the current RCS - we need a DIFFERENT one
                    if rcs_id == current_rcs:
                        print(f"DEBUG: Skipping current RCS {rcs_id}")
                        continue
                    
                    # Check if DS marker is present
                    if 'DS' in channelset:
                        # Get the channel range list (everything after 'DS')
                        ds_index = channelset.index('DS')
                        channel_ranges_str = ' '.join(channelset[ds_index+1:])
                        
                        # Check if NONE of the impaired channels are in this set
                        has_impaired = any(channel_in_range_list(ch, channel_ranges_str) for ch in impaired_list)
                        
                        if not has_impaired:
                            
                            # If target_channels specified, verify exact match
                            if target_channels:
                                # Expand this RCS's channels and compare
                                rcs_channel_list = channelset[ds_index+1:]
                                rcs_expanded = expand_channel_ranges(rcs_channel_list)
                                
                                if set(rcs_expanded) == set(target_channels):
                                    print(f"DEBUG: Found RCS {rcs_id} with exact matching channels ({len(rcs_expanded)} channels)")
                                    return rcs_id
                                else:
                                    print(f"DEBUG: RCS {rcs_id} has {len(rcs_expanded)} channels but doesn't match target {len(target_channels)} channels, skipping")
                                    continue
                            else:
                                # No target specified, just return first RCS without impaired channels
                                print(f"DEBUG: Found alternate RCS {rcs_id} without any impaired channel")
                                return rcs_id
                            print(f"DEBUG: Found alternate RCS {rcs_id} without impaired channel ({len(rcs_channels)}+ channels)")
                            return rcs_id
            
            # If we didn't find an alternate RCS without the impaired channel,
            # we need to create one by building a channel list
            print(f"DEBUG: No existing alternate RCS found without impaired channel meeting requirements")
            return None
            
    except Exception as e:
        print("An error occurred while getting channel set:", str(e))
        return None

def get_impaired_cm(cmts_connect):
    try:
        command_output = send_command(cmts_connect, 'show cable modem bonded-impaired ofdm-downstream | include (D9|D1[1-3])/*/[40-42]|(D9|D1[1-3])/ofd')
        parsed_data = []
        modem_data = {}  # Track unique modem+channel combinations
        modem_impairments = {}  # Track all impairments per modem MAC
        
        if command_output:
            for line in command_output.split('\n'):
                if line.strip():
                    fields = line.split()
                    
                    # Check if line has enough fields
                    if len(fields) >= 8:
                        # Extract bonding info
                        # fields[2] = Bonded (expected, e.g., 32x5)
                        # fields[3] = Actual (impaired, e.g., 31x5)
                        bonded = fields[2]
                        actual_bonding = fields[3]
                        
                        # Extract impaired channel info (field[4])
                        impaired_channel_info = fields[4]
                        
                        # Check if it's a downstream impairment (starts with D)
                        if impaired_channel_info.startswith('D'):
                            # Parse bonding numbers
                            actual_match = re.match(r'(\d+)x(\d+)', actual_bonding)
                            bonded_match = re.match(r'(\d+)x(\d+)', bonded)
                            
                            if actual_match and bonded_match:
                                actual_ds = int(actual_match.group(1))
                                bonded_ds = int(bonded_match.group(1))
                                
                                # Check if downstream is impaired (actual < bonded)
                                if actual_ds < bonded_ds:
                                    # Parse impaired channel
                                    # Format: "D12/ofd/1*" or "D12/0/40*" or "D12/0/41*" -> extract channel part
                                    channel_match = re.search(r'D(.+?)(?:\*|$)', impaired_channel_info)
                                    if channel_match:
                                        channel = channel_match.group(1)
                                        
                                        # Check if it's OFDM channel:
                                        # - Has '/ofd/' in path (CCCAP linecard format)
                                        # - OR ends with /40 or /41 (ICCAP linecard format - OFDM channels)
                                        # - /42 is reserved for future OFDM channels
                                        is_ofdm_cccap = '/ofd/' in channel
                                        is_ofdm_iccap = channel.endswith('/40') or channel.endswith('/41')
                                        
                                        if not (is_ofdm_iccap or is_ofdm_cccap):
                                            continue
                                        
                                        ds_intf = fields[0]
                                        # Strip leading '+' from interface (indicates multiple impairments)
                                        if ds_intf.startswith('+'):
                                            ds_intf = ds_intf[1:]
                                        
                                        # Cable-mac is in fields[1] (e.g., "107", "126")
                                        cablemac = fields[1]
                                        cm_mac = fields[7]
                                        
                                        # Create unique key for this modem+channel combination
                                        unique_key = f"{cm_mac}:{channel}"
                                        
                                        # Only process if we haven't seen this combination before
                                        if unique_key not in modem_data:
                                            # Track all impairments for this modem
                                            if cm_mac not in modem_impairments:
                                                modem_impairments[cm_mac] = set()
                                            modem_impairments[cm_mac].add(channel)
                                            
                                            # Store this unique combination
                                            modem_data[unique_key] = {
                                                'Interface': ds_intf,
                                                'CableMac': cablemac,
                                                'Channel': channel,
                                                'CM': cm_mac,
                                                'Bonded': bonded
                                            }
            
            # Now create the final entries - ONE per modem (not per channel)
            # Each modem entry contains all its impaired channels
            processed_modems = set()
            for unique_key, data in modem_data.items():
                cm_mac = data['CM']
                
                # Skip if we already processed this modem
                if cm_mac in processed_modems:
                    continue
                processed_modems.add(cm_mac)
                
                impairment_count = len(modem_impairments[cm_mac])
                all_impaired = ','.join(sorted(modem_impairments[cm_mac]))
                
                # Use the first impaired channel as the primary one
                # (for backward compatibility with existing code)
                first_channel = sorted(modem_impairments[cm_mac])[0]
                
                extracted_values = {
                    'Interface': data['Interface'],
                    'CableMac': data['CableMac'],
                    'Channel': first_channel,  # Primary impaired channel
                    'CM': cm_mac,
                    'Bonded': data['Bonded'],
                    'ImpairmentCount': impairment_count,
                    'AllImpairedChannels': all_impaired
                }
                parsed_data.append(extracted_values)
            
            return parsed_data  
        else:
            print("Failed to retrieve command output.")
            return None
    except Exception as e:
        print("An error occurred:", str(e))
        return None


def check_bonding_group(cmts_connect, cablemac, impaired_channel, ds_interface, cm_mac):
    """
    Find the impaired OFDM downstream channel ID and build channel set excluding it.
    Returns dict with channel_id and channel set.
    """
    try:
        # First, get the modem's current RCS ID
        print(f"DEBUG: Getting RCS for modem {cm_mac}")
        modem_output = send_command(cmts_connect, f'show cable modem {cm_mac} verbose | include RCS')
        current_rcs = None
        
        if modem_output:
            print(f"DEBUG: Modem output received, length: {len(modem_output)}")
            # Look for RCS=0x010000ab in the output
            rcs_match = re.search(r'RCS=(0x[0-9a-fA-F]+)', modem_output)
            if rcs_match:
                current_rcs = rcs_match.group(1)
                print(f"DEBUG: Modem {cm_mac} is using RCS {current_rcs}")
            else:
                print(f"Could not find RCS for modem {cm_mac}")
                print(f"DEBUG: First 500 chars: {modem_output[:500]}")
                return None
        else:
            print(f"Failed to get modem info for {cm_mac}")
            return None
        
        # Now get the channel sets
        command_output = send_command(cmts_connect, 'show cable channel-sets cable-mac '+cablemac+' ds')
        if command_output:
            # impaired_channel is now in format "12/ofd/1" (already has cable interface)
            # No need to parse and rebuild it
            impaired_full = impaired_channel
            
            print(f"DEBUG: Looking for impaired channel: {impaired_full} in RCS {current_rcs}")
            
            # Parse the output - look for the specific RCS
            lines = command_output.split('\n')
            current_channels = []
            found_rcs = False
            
            for i, line in enumerate(lines):
                line = line.strip()
                
                # Check if this line has the RCS we're looking for
                if line.startswith(cablemac) and current_rcs in line:
                    found_rcs = True
                    parts = line.split()
                    
                    if len(parts) >= 3 and 'DS' in parts:
                        # Get all channels after 'DS'
                        ds_index = parts.index('DS')
                        current_channels = parts[ds_index+1:]
                        print(f"DEBUG: Found RCS {current_rcs}, reading channels...")
                
                # Check for continuation lines (only if we found the right RCS)
                elif found_rcs and line and not line.startswith(cablemac):
                    # This is a continuation line with more channels
                    if '/' in line:  # Channel format contains '/'
                        continuation_channels = line.split()
                        current_channels.extend(continuation_channels)
                    else:
                        # End of this RCS's channels
                        break
                
                # If we found another RCS line, we're done with our RCS
                elif found_rcs and line.startswith(cablemac):
                    break
            
            if not found_rcs or not current_channels:
                print(f"Could not find RCS {current_rcs} for cable-mac {cablemac}")
                print(f"DEBUG: found_rcs={found_rcs}, current_channels has {len(current_channels)} entries")
                return None
            
            # Check if the impaired channel is in this RCS
            if impaired_full not in current_channels:
                print(f"WARNING: Impaired channel {impaired_full} not found in current RCS {current_rcs}")
                print(f"This might indicate the modem already moved to a different channel set")
                return None
            
            # Remove the impaired channel from the list
            new_channels = [ch for ch in current_channels if ch != impaired_full]
            
            # Check if we have any channels left after removing the impaired one
            if len(new_channels) == 0:
                print(f"ERROR: After removing impaired channel {impaired_full}, no channels remain in RCS {current_rcs}")
                print(f"This modem only has access to the impaired channel - cannot create valid channel set")
                return None
            
            # Build the new channel set string
            channel_set = ' '.join(new_channels)
            
            print(f"Found impaired channel {impaired_full} in RCS {current_rcs}")
            print(f"Original channels ({len(current_channels)}): {' '.join(current_channels[:5])}...")
            print(f"New channel set ({len(new_channels)} channels, impaired {impaired_full} removed)")
            print(f"DEBUG: Full new channel set: {channel_set}")
            
            return {
                'impaired_channel': impaired_full,
                'rcp_id': current_rcs,
                'channel_set': channel_set,
                'channel_count': len(new_channels)
            }
        else:
            print("Failed to retrieve command output.")
            return None  
    except Exception as e:
        print("An error occurred:", str(e))
        return None


def dbc_impaired_cm(cmts_connect, cmmac, channelset, dry_run=False):
    try:
        command = f'configure cable modem move {cmmac} downstream-channel-set-id {channelset} method direct'
        
        if dry_run:
            print(f"DEBUG: [DRY RUN] Would execute DBC command: {command}")
            return "[DRY RUN] DBC command not executed"
        else:
            print(f"DEBUG: Executing DBC command: {command}")
            dbc_command = send_command(cmts_connect, command)
            print(f"DEBUG: DBC output received: {dbc_command if dbc_command else 'No output'}")
            return(dbc_command)
    except Exception as e:
        print("An error occurred while sending command:", str(e))
        return None


def fix_impaired_cm(cmts_connect, host, impaired_cm, cnx, dry_run=False):
    for entry in impaired_cm:
        impairment_info = f"({entry['ImpairmentCount']} impaired)" if entry['ImpairmentCount'] > 1 else ""
        print(f"Thread ID: {threading.get_ident()} - {host} - Impaired modem found Cable-Mac: {entry['CableMac']}  CM-Interface: {entry['Interface']}  Impaired chan: {entry['Channel']} CM Macaddress: {entry['CM']} {impairment_info}")
    
    for entry in impaired_cm:
        print(f"Thread ID: {threading.get_ident()} - {host} - Checking cable-mac {entry['CableMac']} with impaired modem {entry['CM']} for impaired DS channel {entry['Channel']}")
        
        if entry['ImpairmentCount'] > 1:
            print(f"WARNING: Modem {entry['CM']} has {entry['ImpairmentCount']} impaired OFDM channels: {entry['AllImpairedChannels']}")
        
        # Get modem's load balancing group and downstream service group
        cm_lb_group = get_cm_lb_group(cmts_connect, entry['CM'])
        cm_mdssg = get_cm_mdssg(cmts_connect, entry['CM'])
        
        if cm_lb_group and cm_mdssg:
            print(f"Thread ID: {threading.get_ident()} - {host} - Modem {entry['CM']}: LB Group={cm_lb_group}, mDSsg={cm_mdssg}")
            
            # Find or create alternate bonding group without impaired channel
            alternate_group = find_alternate_ds_bonding_group(cmts_connect, entry['CableMac'], entry['AllImpairedChannels'], cm_lb_group, cm_mdssg, entry['CM'])
            
            if not alternate_group:
                print(f"Thread ID: {threading.get_ident()} - {host} - Modem {entry['CM']}: Could not find or create alternate bonding group, skipping")
                continue
            
            if alternate_group['type'] == 'existing':
                print(f"Thread ID: {threading.get_ident()} - {host} - Found existing DS bonding group {alternate_group['group_id']} to use")
                print(f"DEBUG: Group channels: {' '.join(alternate_group['channels'])}")
                if alternate_group.get('tcs'):
                    print(f"DEBUG: Using TCS {alternate_group['tcs']} for upstream channels")
            elif alternate_group['type'] == 'create':
                print(f"Thread ID: {threading.get_ident()} - {host} - Need to create new DS bonding group")
                print(f"DEBUG: Config: {alternate_group['config']}")
                # E6000 executes commands directly without config mode
                try:
                    result = send_command(cmts_connect, alternate_group['config'])
                    if result is None:
                        print(f"ERROR: Bonding group creation command failed (no connection/timeout), skipping modem {entry['CM']}")
                        continue
                    
                    # E6000 returns just prompt (empty or minimal) on success, or error text on failure
                    if 'error' in result.lower() or 'invalid' in result.lower() or 'failed' in result.lower():
                        print(f"ERROR: Bonding group creation failed: {result}, skipping modem {entry['CM']}")
                        continue
                    else:
                        print(f"Thread ID: {threading.get_ident()} - {host} - Bonding group created successfully")
                        print(f"DEBUG: Command result: '{result}'")
                except Exception as e:
                    print(f"ERROR: Failed to create bonding group: {str(e)}, skipping modem {entry['CM']}")
                    continue
            
            # Try to get an existing channel set that matches the bonding group channels
            target_channels = None
            if alternate_group and 'channels' in alternate_group:
                # Expand the bonding group's channels to get the full list
                target_channels = expand_channel_ranges(alternate_group['channels'])
                print(f"DEBUG: Looking for RCS with {len(target_channels)} channels matching bonding group")
            
            # Use AllImpairedChannels for RCS lookup (contains all impaired channels)
            new_rcs = get_cm_channel_set(cmts_connect, entry['CableMac'], entry['AllImpairedChannels'], entry['Interface'], entry['CM'], target_channels)
            
            if new_rcs:
                # Found existing RCS without impaired channel, use it directly
                print(f"Thread ID: {threading.get_ident()} - {host} - Modem {entry['CM']}: Using existing RCS {new_rcs}, starting DBC")
                
                # Get modem's original RCS before DBC
                modem_output = send_command(cmts_connect, f'show cable modem {entry["CM"]} verbose | include RCS')
                original_rcs = None
                if modem_output:
                    rcs_match = re.search(r'RCS=(0x[0-9a-fA-F]+)', modem_output)
                    if rcs_match:
                        original_rcs = rcs_match.group(1)
                        print(f"DEBUG: Storing original RCS {original_rcs} for modem {entry['CM']}")
                
                # Insert one DB row per impaired channel
                if not dry_run:
                    for impaired_ch in entry['AllImpairedChannels'].split(','):
                        mysql_insert(cnx, host, entry['CableMac'], entry['Interface'], impaired_ch.strip(), entry['CM'], entry['ImpairmentCount'], entry['AllImpairedChannels'], original_rcs)
                else:
                    print(f"DEBUG: [DRY RUN] Would insert {entry['ImpairmentCount']} DB rows for modem {entry['CM']}")
                
                dbc_status = dbc_impaired_cm(cmts_connect, entry['CM'], new_rcs, dry_run)
                if dbc_status and 'Sending DBC-REQ' in dbc_status:
                    print(f"Thread ID: {threading.get_ident()} - {host} - DBC completed for modem {entry['CM']}")
            else:
                print(f"Thread ID: {threading.get_ident()} - {host} - Modem {entry['CM']}: No suitable RCS found without impaired channel")
        else:
            print(f"Thread ID: {threading.get_ident()} - {host} - Modem {entry['CM']}: Could not get LB Group or mDSsg, skipping")


def decryptpwd(encpwd):
    refkeybyt = bytes('Z4gJ36cWp4tVJXKROVzNpn_MC8OVwMJpTR_O-NIDCrw=','utf-8')
    encpwdbyt = bytes(encpwd, 'utf-8')
    keytouse = Fernet(refkeybyt)
    passwd = (keytouse.decrypt(encpwdbyt))
    return(passwd.decode('utf-8'))


# Define Username  
username = 'verB0uwen'

# Define Encrypted Password 
enc_password = 'gAAAAABpMq5rKzVjsefcVVN4TvBUnlzXAHs28B_C2mWt3TbEQN-Ua2QPoKEbcXQYa_ruCFQe_POpWp_UzTndbx3FPfJGPg7czQ=='
password = decryptpwd(enc_password).strip()

cmts_connection = None

# Connect to the cmts 
def loop_devices(cmts, pool, dry_run=False):
    host = cmts
    cmts_connection = connect_to_cmts(cmts, username, password)
    if cmts_connection:
        impaired_cm_found = False
    while True:
        try:
           cnx = pool.get_connection() 
           impaired_cm = get_impaired_cm(cmts_connection)
           if impaired_cm:
              impaired_cm_found = True
              fix_impaired_cm(cmts_connection, host, impaired_cm, cnx, dry_run)
              break
           else:
               print(f"Thread ID: {threading.get_ident()} - {cmts} - No DS impaired modems online")
               break
        finally:
           if cnx:
             cnx.close() 

def main():
  DEBUG = False
  DRY_RUN = True  # Set to False to actually execute DBC commands and create bonding groups
  
  if DRY_RUN:
      print("=" * 80)
      print("RUNNING IN DRY RUN MODE - No DBC commands or bonding groups will be created")
      print("Set DRY_RUN = False in main() to execute actual modem moves")
      print("=" * 80)
  
  pool = create_mysql_pool()
  try:
     cmtslist = get_devices(pool)
     if cmtslist:
         # Remove duplicates to prevent multiple threads connecting to same CMTS
         unique_cmtslist = list(set(cmtslist))
         if len(unique_cmtslist) < len(cmtslist):
             print(f"WARNING: Removed {len(cmtslist) - len(unique_cmtslist)} duplicate CMTS entries")
         print(f"Processing {len(unique_cmtslist)} unique CMTS devices")
         
         with ThreadPoolExecutor(max_workers=10) as executor:
             futures = [executor.submit(loop_devices, cmts, pool, DRY_RUN) for cmts in unique_cmtslist]
         for future in as_completed(futures):
             future.result()

  finally: 
         print("All tasks completed.")

if __name__ == "__main__":
    main()
