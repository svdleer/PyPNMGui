#!/usr/bin/env python3
"""
Spectrum Analyzer Visualization using Matplotlib
Displays cable modem spectrum data from PyPNM captures
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import argparse
from pathlib import Path


def load_spectrum_data(json_file: str) -> dict:
    """Load spectrum data from JSON file."""
    with open(json_file, 'r') as f:
        data = json.load(f)
    return data


def format_freq(x, pos):
    """Format frequency axis as MHz."""
    return f'{x/1e6:.0f}'


def plot_spectrum(frequencies: list, magnitudes: list, 
                  title: str = "Spectrum Analyzer",
                  save_path: str = None,
                  show_grid: bool = True,
                  color: str = '#00ff00',
                  dark_theme: bool = True):
    """
    Create a spectrum analyzer plot using matplotlib.
    
    Args:
        frequencies: List of frequency values in Hz
        magnitudes: List of magnitude values in dB
        title: Plot title
        save_path: Path to save PNG file (optional)
        show_grid: Whether to show grid lines
        color: Line color (default green like traditional spectrum analyzers)
        dark_theme: Use dark background theme
    """
    # Convert to numpy arrays for efficiency
    freqs = np.array(frequencies)
    mags = np.array(magnitudes)
    
    # Set up the plot style
    if dark_theme:
        plt.style.use('dark_background')
        bg_color = '#1a1a2e'
        grid_color = '#444466'
        text_color = '#cccccc'
    else:
        plt.style.use('default')
        bg_color = 'white'
        grid_color = '#cccccc'
        text_color = 'black'
    
    # Create figure with spectrum analyzer proportions
    fig, ax = plt.subplots(figsize=(14, 6), dpi=100)
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    # Plot the spectrum
    ax.plot(freqs, mags, color=color, linewidth=0.5, alpha=0.9)
    
    # Fill under the curve for that classic spectrum analyzer look
    ax.fill_between(freqs, mags, mags.min() - 5, color=color, alpha=0.2)
    
    # Configure axes
    ax.set_xlabel('Frequency (MHz)', fontsize=12, color=text_color)
    ax.set_ylabel('Power Level (dBmV)', fontsize=12, color=text_color)
    ax.set_title(title, fontsize=14, fontweight='bold', color=text_color, pad=15)
    
    # Format x-axis to show MHz
    ax.xaxis.set_major_formatter(FuncFormatter(format_freq))
    
    # Set axis limits with some padding
    ax.set_xlim(freqs.min(), freqs.max())
    y_min, y_max = mags.min() - 5, mags.max() + 5
    ax.set_ylim(y_min, y_max)
    
    # Grid styling
    if show_grid:
        ax.grid(True, linestyle='--', alpha=0.5, color=grid_color)
        ax.minorticks_on()
        ax.grid(True, which='minor', linestyle=':', alpha=0.2, color=grid_color)
    
    # Customize tick colors
    ax.tick_params(colors=text_color)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
    
    # Add frequency range annotation
    freq_range_text = f'Range: {freqs.min()/1e6:.1f} - {freqs.max()/1e6:.1f} MHz'
    ax.annotate(freq_range_text, xy=(0.02, 0.98), xycoords='axes fraction',
                fontsize=10, color=text_color, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor=bg_color, alpha=0.8, edgecolor=grid_color))
    
    # Add statistics annotation
    stats_text = f'Peak: {mags.max():.1f} dBmV @ {freqs[np.argmax(mags)]/1e6:.1f} MHz\nMin: {mags.min():.1f} dBmV'
    ax.annotate(stats_text, xy=(0.98, 0.98), xycoords='axes fraction',
                fontsize=10, color=text_color, verticalalignment='top',
                horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor=bg_color, alpha=0.8, edgecolor=grid_color))
    
    plt.tight_layout()
    
    # Save if path provided
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight',
                    facecolor=bg_color, edgecolor='none')
        print(f"Saved spectrum plot to: {save_path}")
    
    return fig, ax


def plot_spectrum_from_json(json_file: str, save_path: str = None, show: bool = True):
    """
    Load spectrum data from JSON and create visualization.
    
    Args:
        json_file: Path to spec.json file
        save_path: Optional path to save PNG
        show: Whether to display the plot
    """
    print(f"Loading spectrum data from: {json_file}")
    data = load_spectrum_data(json_file)
    
    # Extract signal analysis data
    analysis = data.get('data', {}).get('analysis', [])
    if not analysis:
        raise ValueError("No analysis data found in JSON file")
    
    signal_analysis = analysis[0].get('signal_analysis', {})
    frequencies = signal_analysis.get('frequencies', [])
    magnitudes = signal_analysis.get('magnitudes', [])
    
    if not frequencies or not magnitudes:
        raise ValueError("No frequency/magnitude data found")
    
    print(f"Loaded {len(frequencies)} data points")
    print(f"Frequency range: {frequencies[0]/1e6:.2f} - {frequencies[-1]/1e6:.2f} MHz")
    print(f"Magnitude range: {min(magnitudes):.2f} - {max(magnitudes):.2f} dBmV")
    
    # Get device info for title
    device_details = analysis[0].get('device_details', {})
    system_desc = device_details.get('system_description', {})
    model = system_desc.get('MODEL', 'Unknown')
    vendor = system_desc.get('VENDOR', 'Unknown')
    
    title = f"RF Spectrum Analysis - {vendor} {model}"
    
    # Create the plot
    fig, ax = plot_spectrum(
        frequencies=frequencies,
        magnitudes=magnitudes,
        title=title,
        save_path=save_path,
        dark_theme=True
    )
    
    if show:
        plt.show()
    
    return fig, ax


def plot_spectrum_waterfall(json_file: str, save_path: str = None, show: bool = True):
    """
    Create a single-trace waterfall-style visualization.
    Shows spectrum as a color-mapped image for channel identification.
    """
    data = load_spectrum_data(json_file)
    signal_analysis = data['data']['analysis'][0]['signal_analysis']
    frequencies = np.array(signal_analysis['frequencies'])
    magnitudes = np.array(signal_analysis['magnitudes'])
    
    # Create figure
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), 
                                     gridspec_kw={'height_ratios': [2, 1]})
    
    plt.style.use('dark_background')
    fig.patch.set_facecolor('#1a1a2e')
    
    # Top plot: Color-coded spectrum (waterfall single line)
    # Create a 2D representation for imshow
    mag_2d = magnitudes.reshape(1, -1)
    
    extent = [frequencies.min()/1e6, frequencies.max()/1e6, 0, 1]
    im = ax1.imshow(mag_2d, aspect='auto', cmap='viridis', 
                    extent=extent, interpolation='bilinear')
    ax1.set_xlabel('Frequency (MHz)')
    ax1.set_yticks([])
    ax1.set_title('RF Spectrum Heat Map', fontsize=12, fontweight='bold')
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax1, orientation='vertical', pad=0.02)
    cbar.set_label('Power (dBmV)', fontsize=10)
    
    # Bottom plot: Traditional line plot
    ax2.plot(frequencies/1e6, magnitudes, color='#00ff00', linewidth=0.5)
    ax2.fill_between(frequencies/1e6, magnitudes, magnitudes.min(), 
                     color='#00ff00', alpha=0.2)
    ax2.set_xlabel('Frequency (MHz)')
    ax2.set_ylabel('Power (dBmV)')
    ax2.set_title('RF Spectrum Line Plot', fontsize=12, fontweight='bold')
    ax2.grid(True, linestyle='--', alpha=0.3)
    ax2.set_xlim(frequencies.min()/1e6, frequencies.max()/1e6)
    
    for ax in [ax1, ax2]:
        ax.set_facecolor('#1a1a2e')
    
    plt.tight_layout()
    
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight', 
                    facecolor='#1a1a2e')
        print(f"Saved waterfall plot to: {save_path}")
    
    if show:
        plt.show()
    
    return fig


def main():
    parser = argparse.ArgumentParser(description='Spectrum Analyzer Visualization')
    parser.add_argument('json_file', nargs='?', default='spec.json',
                        help='Path to spectrum JSON file (default: spec.json)')
    parser.add_argument('-o', '--output', type=str, default=None,
                        help='Output PNG file path')
    parser.add_argument('--waterfall', action='store_true',
                        help='Create waterfall-style visualization')
    parser.add_argument('--no-show', action='store_true',
                        help='Do not display the plot (useful for saving only)')
    
    args = parser.parse_args()
    
    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"Error: File not found: {json_path}")
        return 1
    
    try:
        if args.waterfall:
            plot_spectrum_waterfall(
                str(json_path),
                save_path=args.output,
                show=not args.no_show
            )
        else:
            plot_spectrum_from_json(
                str(json_path),
                save_path=args.output,
                show=not args.no_show
            )
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
