"""
UTSC Spectrum Plotter for PyPNM Web GUI
Generates matplotlib plots for Upstream Spectrum Capture (UTSC) data
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


def generate_utsc_plot(
    frequencies: List[float],
    amplitudes: List[float],
    mac_address: str = "",
    rf_port_description: str = "",
    capture_params: Optional[Dict[str, Any]] = None,
    max_hold_amplitudes: Optional[List[float]] = None
) -> bytes:
    """
    Generate a matplotlib UTSC spectrum plot matching PyPNM dark theme style.
    
    Args:
        frequencies: List of frequency values in Hz
        amplitudes: List of amplitude values in dBmV  
        mac_address: Modem MAC address for title
        rf_port_description: RF port description (e.g., "MNDGT0002RPS01-0 us-conn 0")
        capture_params: Capture parameters for annotations
        max_hold_amplitudes: Optional max hold amplitude values
        
    Returns:
        PNG image as bytes
    """
    # Convert to numpy arrays
    freqs = np.array(frequencies)
    amps = np.array(amplitudes)
    
    # Clamp amplitudes to minimum of 0 dBmV (no negative spikes displayed)
    amps = np.clip(amps, 0, None)
    
    # PyPNM dark theme colors
    bg_color = '#1e1e2e'
    plot_bg = '#2d2d3d'
    grid_color = '#404050'
    text_color = '#e0e0e0'
    line_color = '#00aaff'  # Blue for UTSC
    fill_color = 'rgba(0, 170, 255, 0.15)'
    
    # Set up matplotlib style
    plt.style.use('dark_background')
    
    # Create figure matching PyPNM plot dimensions
    fig, ax = plt.subplots(figsize=(14, 6), dpi=100)
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(plot_bg)
    
    # Plot the spectrum line
    ax.plot(freqs, amps, color=line_color, linewidth=1.0, alpha=0.9, label='Current')
    
    # Plot max hold if provided
    if max_hold_amplitudes is not None:
        max_hold = np.array(max_hold_amplitudes)
        max_hold = np.clip(max_hold, 0, None)  # Also clamp max hold to 0
        ax.plot(freqs, max_hold, color='#ff6600', linewidth=1.0, alpha=0.7, 
                linestyle='--', label='Max Hold')
    
    # Fill under the curve
    ax.fill_between(freqs, amps, 0, color=line_color, alpha=0.15)
    
    # Configure axes
    ax.set_xlabel('Frequency (MHz)', fontsize=11, color=text_color, labelpad=10)
    ax.set_ylabel('Power Level (dBmV)', fontsize=11, color=text_color, labelpad=10)
    
    # Build title
    title_parts = ['UTSC - Upstream Spectrum Capture']
    if rf_port_description:
        title_parts.append(f"- {rf_port_description}")
    if mac_address:
        title_parts.append(f"[{mac_address}]")
    
    ax.set_title(' '.join(title_parts), fontsize=13, fontweight='bold', 
                 color=text_color, pad=15)
    
    # Format x-axis to show MHz
    ax.xaxis.set_major_formatter(FuncFormatter(format_freq_mhz))
    
    # Set axis limits - Y axis always starts at 0 (no negative values)
    ax.set_xlim(freqs.min(), freqs.max())
    y_max = max(amps.max(), 10) + 5  # At least show up to 10 dBmV
    if max_hold_amplitudes is not None:
        y_max = max(y_max, np.max(max_hold_amplitudes) + 5)
    ax.set_ylim(0, y_max)
    
    # Add legend if max hold is shown
    if max_hold_amplitudes is not None:
        ax.legend(loc='upper right', fontsize=9, facecolor=plot_bg, 
                  edgecolor=grid_color, labelcolor=text_color)
    
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
    peak_idx = np.argmax(amps)
    
    # Use configured span if available, otherwise calculate from data
    if capture_params and 'span_hz' in capture_params:
        span_mhz = capture_params['span_hz'] / 1e6
    else:
        span_mhz = (freqs.max() - freqs.min()) / 1e6
    
    stats_text = (f'Peak: {amps.max():.1f} dBmV @ {freqs[peak_idx]/1e6:.1f} MHz\n'
                  f'Min: {amps.min():.1f} dBmV | Avg: {amps.mean():.1f} dBmV\n'
                  f'Span: {span_mhz:.1f} MHz')
    ax.annotate(stats_text, xy=(0.98, 0.97), xycoords='axes fraction',
                fontsize=9, color=text_color, verticalalignment='top',
                horizontalalignment='right',
                bbox=dict(boxstyle='round,pad=0.4', facecolor=plot_bg, 
                         alpha=0.9, edgecolor=grid_color))
    
    # Add capture parameters if available (bottom-left)
    if capture_params:
        num_bins = capture_params.get('num_bins', len(amps))
        center_freq = capture_params.get('center_freq_hz', (freqs.min() + freqs.max()) / 2)
        param_text = (f"Bins: {num_bins} | "
                      f"Center: {center_freq/1e6:.1f} MHz | "
                      f"Points: {len(freqs):,}")
        ax.annotate(param_text, xy=(0.02, 0.03), xycoords='axes fraction',
                    fontsize=8, color='#888888', verticalalignment='bottom',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor=plot_bg, 
                             alpha=0.8, edgecolor=grid_color))
    
    plt.tight_layout()
    
    # Save to bytes
    buf = BytesIO()
    try:
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                    facecolor=bg_color, edgecolor='none')
        buf.seek(0)
        image_data = buf.getvalue()
    finally:
        # Ensure figure is closed and memory is freed
        plt.close(fig)
        plt.clf()
        buf.close()
    
    return image_data


def generate_utsc_plot_from_data(
    data: Dict[str, Any], 
    mac_address: str = "",
    rf_port_description: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Generate UTSC spectrum plot from measurement data.
    
    Args:
        data: UTSC spectrum measurement response data
        mac_address: Modem MAC address
        rf_port_description: RF port description
        
    Returns:
        Dict with filename and base64-encoded PNG data, or None if failed
    """
    try:
        frequencies = data.get('frequencies', [])
        amplitudes = data.get('amplitudes', [])
        
        if not frequencies or not amplitudes:
            logger.warning("No frequency/amplitude data found")
            return None
        
        logger.info(f"Generating UTSC plot: {len(frequencies)} points, "
                   f"{frequencies[0]/1e6:.1f} - {frequencies[-1]/1e6:.1f} MHz")
        
        # Build capture params with span if available
        capture_params = {
            'num_bins': data.get('num_bins', data.get('num_samples', len(amplitudes))),
            'center_freq_hz': data.get('center_freq_hz', (frequencies[0] + frequencies[-1]) / 2) if frequencies else 0
        }
        
        # Add span if provided in data
        if 'span_hz' in data:
            capture_params['span_hz'] = data['span_hz']
        
        # Generate the plot
        png_bytes = generate_utsc_plot(
            frequencies=frequencies,
            amplitudes=amplitudes,
            mac_address=mac_address,
            rf_port_description=rf_port_description,
            capture_params=capture_params
        )
        
        # Create filename
        import time
        mac_clean = mac_address.replace(':', '').lower()
        timestamp = int(time.time())
        filename = f"{mac_clean}_utsc_{timestamp}.png"
        
        return {
            'filename': filename,
            'data': base64.b64encode(png_bytes).decode('utf-8')
        }
        
    except Exception as e:
        logger.error(f"Error generating UTSC plot: {e}", exc_info=True)
        return None
