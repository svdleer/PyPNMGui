"""
Spectrum Analyzer Plotter for PyPNM Web GUI
Generates matplotlib plots matching the style of other PNM measurements
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server use
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from typing import Dict, Any, List, Optional
import base64
from io import BytesIO
import logging

logger = logging.getLogger(__name__)


def format_freq_mhz(x, pos):
    """Format frequency axis as MHz."""
    return f'{x/1e6:.0f}'


def generate_spectrum_plot(
    frequencies: List[float],
    magnitudes: List[float],
    mac_address: str = "",
    device_info: Optional[Dict[str, Any]] = None,
    capture_params: Optional[Dict[str, Any]] = None
) -> bytes:
    """
    Generate a matplotlib spectrum plot matching the PyPNM dark theme style.
    
    Args:
        frequencies: List of frequency values in Hz
        magnitudes: List of magnitude values in dBmV
        mac_address: Modem MAC address for title
        device_info: Device details (VENDOR, MODEL, etc.)
        capture_params: Capture parameters for annotations
        
    Returns:
        PNG image as bytes
    """
    # Convert to numpy arrays
    freqs = np.array(frequencies)
    mags = np.array(magnitudes)
    
    # PyPNM dark theme colors (matching other plots)
    bg_color = '#1e1e2e'
    plot_bg = '#2d2d3d'
    grid_color = '#404050'
    text_color = '#e0e0e0'
    line_color = '#00ff88'  # Green like traditional spectrum analyzers
    fill_color = 'rgba(0, 255, 136, 0.15)'
    
    # Set up matplotlib style
    plt.style.use('dark_background')
    
    # Create figure matching PyPNM plot dimensions
    fig, ax = plt.subplots(figsize=(14, 6), dpi=100)
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(plot_bg)
    
    # Plot the spectrum line
    ax.plot(freqs, mags, color=line_color, linewidth=0.5, alpha=0.9)
    
    # Fill under the curve
    ax.fill_between(freqs, mags, mags.min() - 5, color=line_color, alpha=0.15)
    
    # Configure axes
    ax.set_xlabel('Frequency (MHz)', fontsize=11, color=text_color, labelpad=10)
    ax.set_ylabel('Power Level (dBmV)', fontsize=11, color=text_color, labelpad=10)
    
    # Build title
    title_parts = ['Full Band Spectrum Analysis']
    if device_info:
        vendor = device_info.get('VENDOR', '')
        model = device_info.get('MODEL', '')
        if vendor or model:
            title_parts.append(f"- {vendor} {model}".strip())
    if mac_address:
        title_parts.append(f"[{mac_address}]")
    
    ax.set_title(' '.join(title_parts), fontsize=13, fontweight='bold', 
                 color=text_color, pad=15)
    
    # Format x-axis to show MHz
    ax.xaxis.set_major_formatter(FuncFormatter(format_freq_mhz))
    
    # Set axis limits
    ax.set_xlim(freqs.min(), freqs.max())
    y_min, y_max = mags.min() - 5, mags.max() + 5
    ax.set_ylim(y_min, y_max)
    
    # Grid styling
    ax.grid(True, linestyle='--', alpha=0.4, color=grid_color)
    ax.minorticks_on()
    ax.grid(True, which='minor', linestyle=':', alpha=0.2, color=grid_color)
    
    # Customize tick colors
    ax.tick_params(colors=text_color, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
    
    # Add frequency range annotation (top-left)
    freq_range_text = f'Range: {freqs.min()/1e6:.1f} - {freqs.max()/1e6:.1f} MHz'
    ax.annotate(freq_range_text, xy=(0.02, 0.97), xycoords='axes fraction',
                fontsize=9, color=text_color, verticalalignment='top',
                bbox=dict(boxstyle='round,pad=0.4', facecolor=plot_bg, 
                         alpha=0.9, edgecolor=grid_color))
    
    # Add statistics annotation (top-right)
    peak_idx = np.argmax(mags)
    stats_text = (f'Peak: {mags.max():.1f} dBmV @ {freqs[peak_idx]/1e6:.1f} MHz\n'
                  f'Min: {mags.min():.1f} dBmV | Avg: {mags.mean():.1f} dBmV')
    ax.annotate(stats_text, xy=(0.98, 0.97), xycoords='axes fraction',
                fontsize=9, color=text_color, verticalalignment='top',
                horizontalalignment='right',
                bbox=dict(boxstyle='round,pad=0.4', facecolor=plot_bg, 
                         alpha=0.9, edgecolor=grid_color))
    
    # Add capture parameters if available (bottom-left)
    if capture_params:
        param_text = (f"Bins/Segment: {capture_params.get('num_bins_per_segment', 'N/A')} | "
                      f"Span: {capture_params.get('segment_freq_span', 0)/1e6:.1f} MHz | "
                      f"Points: {len(freqs):,}")
        ax.annotate(param_text, xy=(0.02, 0.03), xycoords='axes fraction',
                    fontsize=8, color='#888888', verticalalignment='bottom',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor=plot_bg, 
                             alpha=0.8, edgecolor=grid_color))
    
    plt.tight_layout()
    
    # Save to bytes
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=bg_color, edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    
    return buf.getvalue()


def generate_spectrum_plot_from_data(data: Dict[str, Any], mac_address: str = "") -> Optional[Dict[str, Any]]:
    """
    Generate spectrum plot from PyPNM measurement data.
    
    Args:
        data: PyPNM spectrum measurement response data
        mac_address: Modem MAC address
        
    Returns:
        Dict with filename and base64-encoded PNG data, or None if failed
    """
    try:
        # Extract analysis data
        analysis_list = data.get('analysis', [])
        if not analysis_list:
            logger.warning("No analysis data found in spectrum response")
            return None
        
        analysis = analysis_list[0]
        signal_analysis = analysis.get('signal_analysis', {})
        
        frequencies = signal_analysis.get('frequencies', [])
        magnitudes = signal_analysis.get('magnitudes', [])
        
        if not frequencies or not magnitudes:
            logger.warning("No frequency/magnitude data found")
            return None
        
        # Get device info and capture params
        device_details = analysis.get('device_details', {})
        device_info = device_details.get('system_description', {})
        capture_params = analysis.get('capture_parameters', {})
        
        logger.info(f"Generating spectrum plot: {len(frequencies)} points, "
                   f"{frequencies[0]/1e6:.1f} - {frequencies[-1]/1e6:.1f} MHz")
        
        # Generate the plot
        png_bytes = generate_spectrum_plot(
            frequencies=frequencies,
            magnitudes=magnitudes,
            mac_address=mac_address,
            device_info=device_info,
            capture_params=capture_params
        )
        
        # Create filename matching PyPNM naming convention
        import time
        mac_clean = mac_address.replace(':', '').lower()
        timestamp = int(time.time())
        filename = f"{mac_clean}_spectrum_{timestamp}.png"
        
        return {
            'filename': filename,
            'data': base64.b64encode(png_bytes).decode('utf-8')
        }
        
    except Exception as e:
        logger.error(f"Failed to generate spectrum plot: {e}", exc_info=True)
        return None


def generate_waterfall_plot(
    frequencies: List[float],
    magnitudes: List[float],
    mac_address: str = "",
    device_info: Optional[Dict[str, Any]] = None
) -> bytes:
    """
    Generate a waterfall/heat-map style spectrum visualization.
    
    Returns:
        PNG image as bytes
    """
    freqs = np.array(frequencies)
    mags = np.array(magnitudes)
    
    # PyPNM dark theme
    bg_color = '#1e1e2e'
    plot_bg = '#2d2d3d'
    text_color = '#e0e0e0'
    grid_color = '#404050'
    
    plt.style.use('dark_background')
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), 
                                   gridspec_kw={'height_ratios': [1, 2]})
    fig.patch.set_facecolor(bg_color)
    
    # Top: Heat map visualization
    ax1.set_facecolor(plot_bg)
    mag_2d = mags.reshape(1, -1)
    extent = [freqs.min()/1e6, freqs.max()/1e6, 0, 1]
    im = ax1.imshow(mag_2d, aspect='auto', cmap='viridis', 
                    extent=extent, interpolation='bilinear')
    ax1.set_xlabel('Frequency (MHz)', color=text_color)
    ax1.set_yticks([])
    ax1.set_title('Spectrum Heat Map', fontsize=11, color=text_color)
    ax1.tick_params(colors=text_color)
    
    # Colorbar
    cbar = plt.colorbar(im, ax=ax1, orientation='vertical', pad=0.02)
    cbar.set_label('Power (dBmV)', color=text_color, fontsize=9)
    cbar.ax.tick_params(colors=text_color)
    
    # Bottom: Line plot
    ax2.set_facecolor(plot_bg)
    ax2.plot(freqs/1e6, mags, color='#00ff88', linewidth=0.5)
    ax2.fill_between(freqs/1e6, mags, mags.min(), color='#00ff88', alpha=0.15)
    ax2.set_xlabel('Frequency (MHz)', color=text_color)
    ax2.set_ylabel('Power (dBmV)', color=text_color)
    ax2.set_title('Spectrum Line Plot', fontsize=11, color=text_color)
    ax2.grid(True, linestyle='--', alpha=0.3, color=grid_color)
    ax2.set_xlim(freqs.min()/1e6, freqs.max()/1e6)
    ax2.tick_params(colors=text_color)
    
    for spine in ax2.spines.values():
        spine.set_color(grid_color)
    
    plt.tight_layout()
    
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=bg_color)
    buf.seek(0)
    plt.close(fig)
    
    return buf.getvalue()
