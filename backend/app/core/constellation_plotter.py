"""
Constellation Display Plotter for PyPNM Web GUI
Generates matplotlib plots matching the style of other PNM measurements
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server use
import matplotlib.pyplot as plt
from typing import Dict, Any, List, Optional, Tuple
import base64
from io import BytesIO
import logging

logger = logging.getLogger(__name__)


def generate_constellation_plot(
    samples: List[Tuple[float, float]],
    channel_id: int,
    mac_address: str = "",
    device_info: Optional[Dict[str, Any]] = None,
    modulation_order: Optional[int] = None,
    subcarrier_freq: Optional[int] = None
) -> bytes:
    """
    Generate a matplotlib constellation plot matching PyPNM dark theme style.
    
    Args:
        samples: List of (I, Q) tuples representing constellation points
        channel_id: OFDM channel ID
        mac_address: Modem MAC address for title
        device_info: Device details (VENDOR, MODEL, etc.)
        modulation_order: Modulation order (e.g., 7 = 128-QAM, 8 = 256-QAM, etc.)
        subcarrier_freq: Subcarrier zero frequency in Hz
        
    Returns:
        PNG image as bytes
    """
    # Extract I and Q values
    i_values = np.array([s[0] for s in samples])
    q_values = np.array([s[1] for s in samples])
    
    # PyPNM dark theme colors (matching other plots)
    bg_color = '#1e1e2e'
    plot_bg = '#2d2d3d'
    grid_color = '#404050'
    text_color = '#e0e0e0'
    point_color = '#ff9f40'  # Orange for constellation points
    
    # Set up matplotlib style
    plt.style.use('dark_background')
    
    # Create square figure for constellation
    fig, ax = plt.subplots(figsize=(8, 8), dpi=100)
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(plot_bg)
    
    # Plot constellation points
    ax.scatter(i_values, q_values, c=point_color, s=2, alpha=0.6, edgecolors='none')
    
    # Add crosshairs at origin
    ax.axhline(y=0, color=grid_color, linewidth=1, alpha=0.8)
    ax.axvline(x=0, color=grid_color, linewidth=1, alpha=0.8)
    
    # Configure axes
    ax.set_xlabel('I (In-Phase)', fontsize=11, color=text_color, labelpad=10)
    ax.set_ylabel('Q (Quadrature)', fontsize=11, color=text_color, labelpad=10)
    
    # Make the plot square with equal aspect ratio
    ax.set_aspect('equal', adjustable='box')
    
    # Set symmetric limits based on data range
    max_range = max(abs(i_values).max(), abs(q_values).max(), 1.5) * 1.1
    ax.set_xlim(-max_range, max_range)
    ax.set_ylim(-max_range, max_range)
    
    # Build title
    modulation_names = {
        6: '64-QAM', 7: '128-QAM', 8: '256-QAM', 9: '512-QAM',
        10: '1024-QAM', 11: '2048-QAM', 12: '4096-QAM'
    }
    mod_name = modulation_names.get(modulation_order, f'Order {modulation_order}') if modulation_order else ''
    
    title_parts = [f'Constellation Display - Channel {channel_id}']
    if mod_name:
        title_parts.append(f'({mod_name})')
    
    ax.set_title(' '.join(title_parts), fontsize=13, fontweight='bold', 
                 color=text_color, pad=15)
    
    # Grid styling
    ax.grid(True, linestyle='--', alpha=0.4, color=grid_color)
    
    # Customize tick colors
    ax.tick_params(axis='both', colors=text_color, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
    
    # Add stats annotation
    stats_text = f'Points: {len(samples):,}'
    if subcarrier_freq:
        stats_text += f'\nFreq: {subcarrier_freq/1e6:.1f} MHz'
    if device_info:
        vendor = device_info.get('VENDOR', '')
        model = device_info.get('MODEL', '')
        if vendor or model:
            stats_text += f'\n{vendor} {model}'.strip()
    if mac_address:
        stats_text += f'\nMAC: {mac_address}'
    
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', color=text_color,
            bbox=dict(boxstyle='round', facecolor=bg_color, alpha=0.8, edgecolor=grid_color))
    
    # Tight layout
    plt.tight_layout()
    
    # Save to bytes
    buf = BytesIO()
    fig.savefig(buf, format='png', facecolor=bg_color, edgecolor='none',
                bbox_inches='tight', pad_inches=0.2)
    buf.seek(0)
    png_bytes = buf.getvalue()
    plt.close(fig)
    
    return png_bytes


def generate_constellation_plots_from_data(data: List[Dict[str, Any]], mac_address: str = "") -> List[Dict[str, Any]]:
    """
    Generate constellation plots from PyPNM constellation data.
    
    Args:
        data: List of constellation measurement dicts from PyPNM, each with:
              - channel_id: OFDM channel ID
              - samples: List of (I, Q) tuples
              - actual_modulation_order: Modulation order
              - subcarrier_zero_frequency: Frequency in Hz
              - device_details: Optional device info
              
    Returns:
        List of dicts with 'filename' and 'data' (base64 PNG)
    """
    plots = []
    
    if not data or not isinstance(data, list):
        logger.warning("No constellation data to plot")
        return plots
    
    for item in data:
        if not isinstance(item, dict):
            continue
            
        channel_id = item.get('channel_id')
        samples = item.get('samples', [])
        
        if not channel_id or not samples:
            logger.warning(f"Skipping constellation item without channel_id or samples")
            continue
        
        try:
            # Extract device info if available
            device_info = None
            device_details = item.get('device_details', {})
            if device_details:
                device_info = device_details.get('system_description', {})
            
            # Generate plot
            png_bytes = generate_constellation_plot(
                samples=samples,
                channel_id=channel_id,
                mac_address=mac_address,
                device_info=device_info,
                modulation_order=item.get('actual_modulation_order'),
                subcarrier_freq=item.get('subcarrier_zero_frequency')
            )
            
            # Base64 encode
            png_b64 = base64.b64encode(png_bytes).decode('utf-8')
            
            # Add to plots list
            mac_clean = mac_address.replace(':', '')
            filename = f"{mac_clean}_constellation_ch{channel_id}.png"
            
            plots.append({
                'filename': filename,
                'data': png_b64,
                'channel_id': channel_id
            })
            
            logger.info(f"Generated constellation plot for channel {channel_id}")
            
        except Exception as e:
            logger.error(f"Failed to generate constellation plot for channel {channel_id}: {e}", exc_info=True)
    
    return plots
