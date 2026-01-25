"""
UTSC Parameter Validation for CommScope E6000 CMTS

Based on E6000 CER User Guide Release 13.0 - Proactive Network Maintenance
and observed behavior from testing.

References:
- DOCS-PNM-MIB (docsPnmCmtsUtscCfg table)
- E6000 CER I-CCAP User Guide
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class UtscLimits:
    """E6000 UTSC parameter limits"""
    
    # Frequency Parameters (Hz)
    MIN_CENTER_FREQ_HZ: int = 5_000_000      # 5 MHz - DOCSIS 3.0 minimum
    MAX_CENTER_FREQ_HZ: int = 200_000_000    # 200 MHz - Extended upstream
    DEFAULT_CENTER_FREQ_HZ: int = 42_500_000 # 42.5 MHz - Center of 0-85 MHz range
    
    # Span Parameters (Hz)
    MIN_SPAN_HZ: int = 1_000_000             # 1 MHz minimum
    MAX_SPAN_HZ: int = 320_000_000           # 320 MHz wideband (if supported)
    DEFAULT_SPAN_HZ: int = 85_000_000        # 85 MHz - Full DOCSIS 3.0 upstream
    SUPPORTED_SPANS_HZ: List[int] = None     # Populated in __post_init__
    
    # Bin Parameters
    MIN_NUM_BINS: int = 64                   # Minimum FFT size
    MAX_NUM_BINS: int = 8192                 # Maximum FFT size (hardware limit)
    DEFAULT_NUM_BINS: int = 3200             # Good resolution for 85 MHz
    SUPPORTED_BIN_COUNTS: List[int] = None   # Populated in __post_init__
    
    # Timing Parameters (milliseconds)
    MIN_REPEAT_PERIOD_MS: int = 0            # 0 = single capture
    MAX_REPEAT_PERIOD_MS: int = 1000         # E6000 limit: 1 second max
    DEFAULT_REPEAT_PERIOD_MS: int = 1000     # 1 second default
    
    MIN_FREERUN_DURATION_MS: int = 0         # 0 = use trigger_count instead
    MAX_FREERUN_DURATION_MS: int = 600_000   # 10 minutes max
    DEFAULT_FREERUN_DURATION_MS: int = 60_000 # 60 seconds
    
    # Trigger Parameters
    MIN_TRIGGER_COUNT: int = 1
    MAX_TRIGGER_COUNT: int = 10              # E6000 hardware limit
    DEFAULT_TRIGGER_COUNT: int = 10
    
    def __post_init__(self):
        """Initialize lists after dataclass creation"""
        # Common span values (MHz converted to Hz)
        self.SUPPORTED_SPANS_HZ = [
            40_000_000,   # 40 MHz - Narrowband
            80_000_000,   # 80 MHz - Common
            85_000_000,   # 85 MHz - Full DOCSIS 3.0
            160_000_000,  # 160 MHz - Wideband
            180_000_000,  # 180 MHz - Extended
            320_000_000,  # 320 MHz - Maximum wideband (if supported)
        ]
        
        # Common bin counts (powers of 2 and common multiples)
        self.SUPPORTED_BIN_COUNTS = [
            64, 128, 256, 512, 800, 1024, 1600, 2048, 3200, 4096, 6400, 8192
        ]


# Global instance
LIMITS = UtscLimits()


class UtscValidationError(Exception):
    """UTSC parameter validation error"""
    pass


def validate_center_frequency(center_freq_hz: int) -> Tuple[bool, Optional[str]]:
    """
    Validate center frequency parameter.
    
    Args:
        center_freq_hz: Center frequency in Hz
        
    Returns:
        (is_valid, error_message)
    """
    if center_freq_hz < LIMITS.MIN_CENTER_FREQ_HZ:
        return False, f"Center frequency {center_freq_hz/1e6:.1f} MHz is below minimum {LIMITS.MIN_CENTER_FREQ_HZ/1e6:.1f} MHz"
    
    if center_freq_hz > LIMITS.MAX_CENTER_FREQ_HZ:
        return False, f"Center frequency {center_freq_hz/1e6:.1f} MHz exceeds maximum {LIMITS.MAX_CENTER_FREQ_HZ/1e6:.1f} MHz"
    
    return True, None


def validate_span(span_hz: int, center_freq_hz: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate frequency span parameter against E6000 CER supported values.
    
    E6000 CER supports specific span values for UTSC:
    - Narrowband FFT: 40 MHz, 80 MHz, 160 MHz
    - Wideband FFT: 80 MHz, 160 MHz, 320 MHz
    
    Args:
        span_hz: Frequency span in Hz
        center_freq_hz: Optional center frequency for range checking
        
    Returns:
        (is_valid, error_message)
    """
    # E6000 CER supported span values (Hz)
    SUPPORTED_SPANS_HZ = [
        40_000_000,   # 40 MHz (Narrowband)
        80_000_000,   # 80 MHz (Both)
        160_000_000,  # 160 MHz (Both)
        320_000_000   # 320 MHz (Wideband)
    ]
    
    if span_hz not in SUPPORTED_SPANS_HZ:
        supported_mhz = [s/1e6 for s in SUPPORTED_SPANS_HZ]
        return False, f"Span {span_hz/1e6:.1f} MHz not supported by E6000. Supported values: {supported_mhz} MHz"
    
    # Check if span + center frequency stays within valid range
    if center_freq_hz is not None:
        freq_start = center_freq_hz - (span_hz / 2)
        freq_end = center_freq_hz + (span_hz / 2)
        
        if freq_start < 0:
            return False, f"Span extends below 0 Hz (start: {freq_start/1e6:.1f} MHz)"
        
        # E6000 narrowband max center: 102 MHz, wideband max center: 204 MHz
        max_center = 204_000_000 if span_hz in [80_000_000, 160_000_000, 320_000_000] else 102_000_000
        if center_freq_hz > max_center:
            return False, f"Center frequency {center_freq_hz/1e6:.1f} MHz exceeds max {max_center/1e6:.1f} MHz for {span_hz/1e6:.1f} MHz span"
    
    return True, None


def validate_num_bins(num_bins: int) -> Tuple[bool, Optional[str]]:
    """
    Validate number of FFT bins against E6000 CER supported values.
    
    E6000 CER supports: 200, 400, 800, 1600, 3200 bins
    
    Args:
        num_bins: Number of FFT bins
        
    Returns:
        (is_valid, error_message)
    """
    # E6000 CER supported num_bins values
    SUPPORTED_NUM_BINS = [200, 400, 800, 1600, 3200]
    
    if num_bins not in SUPPORTED_NUM_BINS:
        return False, f"Number of bins {num_bins} not supported by E6000. Supported values: {SUPPORTED_NUM_BINS}"
    
    # Warn if not a common value
    if num_bins not in LIMITS.SUPPORTED_BIN_COUNTS:
        # Still valid, but not optimal
        closest = min(LIMITS.SUPPORTED_BIN_COUNTS, key=lambda x: abs(x - num_bins))
        warning = f"Bin count {num_bins} is valid but not standard. Closest standard value: {closest}"
        return True, warning
    
    return True, None


def validate_repeat_period(repeat_period_ms: int) -> Tuple[bool, Optional[str]]:
    """
    Validate repeat period parameter.
    
    Args:
        repeat_period_ms: Repeat period in milliseconds
        
    Returns:
        (is_valid, error_message)
    """
    if repeat_period_ms < LIMITS.MIN_REPEAT_PERIOD_MS:
        return False, f"Repeat period {repeat_period_ms}ms is below minimum {LIMITS.MIN_REPEAT_PERIOD_MS}ms"
    
    if repeat_period_ms > LIMITS.MAX_REPEAT_PERIOD_MS:
        return False, f"Repeat period {repeat_period_ms}ms exceeds E6000 maximum of {LIMITS.MAX_REPEAT_PERIOD_MS}ms (1 second)"
    
    return True, None


def validate_freerun_duration(freerun_duration_ms: int) -> Tuple[bool, Optional[str]]:
    """
    Validate free-running duration parameter.
    
    Args:
        freerun_duration_ms: Free-running duration in milliseconds
        
    Returns:
        (is_valid, error_message)
    """
    if freerun_duration_ms < LIMITS.MIN_FREERUN_DURATION_MS:
        return False, f"Free-run duration {freerun_duration_ms}ms is below minimum {LIMITS.MIN_FREERUN_DURATION_MS}ms"
    
    if freerun_duration_ms > LIMITS.MAX_FREERUN_DURATION_MS:
        return False, f"Free-run duration {freerun_duration_ms}ms exceeds maximum {LIMITS.MAX_FREERUN_DURATION_MS}ms (10 minutes)"
    
    return True, None


def validate_trigger_count(trigger_count: int, trigger_mode: int) -> Tuple[bool, Optional[str]]:
    """
    Validate trigger count parameter.
    
    Args:
        trigger_count: Number of triggers
        trigger_mode: Trigger mode (2=FreeRunning, 5=IdleSID, 6=CM_MAC)
        
    Returns:
        (is_valid, error_message)
    """
    # FreeRunning mode uses freerun_duration instead
    if trigger_mode == 2:
        return True, "Trigger count is ignored in FreeRunning mode (uses freerun_duration instead)"
    
    if trigger_count < LIMITS.MIN_TRIGGER_COUNT:
        return False, f"Trigger count {trigger_count} is below minimum {LIMITS.MIN_TRIGGER_COUNT}"
    
    if trigger_count > LIMITS.MAX_TRIGGER_COUNT:
        return False, f"Trigger count {trigger_count} exceeds E6000 maximum of {LIMITS.MAX_TRIGGER_COUNT}"
    
    return True, None


def validate_all_parameters(
    center_freq_hz: int,
    span_hz: int,
    num_bins: int,
    trigger_mode: int = 2,
    repeat_period_ms: int = 1000,
    freerun_duration_ms: int = 60000,
    trigger_count: int = 10
) -> Dict[str, any]:
    """
    Validate all UTSC parameters together.
    
    Returns:
        Dict with:
        - is_valid: bool
        - errors: List[str]
        - warnings: List[str]
    """
    errors = []
    warnings = []
    
    # Validate center frequency
    valid, msg = validate_center_frequency(center_freq_hz)
    if not valid:
        errors.append(msg)
    
    # Validate span (with center frequency check)
    valid, msg = validate_span(span_hz, center_freq_hz)
    if not valid:
        errors.append(msg)
    
    # Validate bins
    valid, msg = validate_num_bins(num_bins)
    if not valid:
        errors.append(msg)
    elif msg:  # Warning
        warnings.append(msg)
    
    # Validate repeat period
    valid, msg = validate_repeat_period(repeat_period_ms)
    if not valid:
        errors.append(msg)
    
    # Validate freerun duration
    valid, msg = validate_freerun_duration(freerun_duration_ms)
    if not valid:
        errors.append(msg)
    
    # Validate trigger count
    valid, msg = validate_trigger_count(trigger_count, trigger_mode)
    if not valid:
        errors.append(msg)
    elif msg:  # Info/Warning
        warnings.append(msg)
    
    # Check frequency resolution
    if span_hz > 0 and num_bins > 0:
        freq_resolution_hz = span_hz / num_bins
        freq_resolution_khz = freq_resolution_hz / 1000
        if freq_resolution_khz > 100:  # > 100 kHz per bin
            warnings.append(f"Frequency resolution {freq_resolution_khz:.1f} kHz/bin may be too coarse. "
                          f"Consider increasing num_bins for better resolution.")
        elif freq_resolution_khz < 10:  # < 10 kHz per bin
            warnings.append(f"Frequency resolution {freq_resolution_khz:.1f} kHz/bin is very fine. "
                          f"Consider decreasing num_bins if not needed.")
    
    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
        'parameters': {
            'center_freq_hz': center_freq_hz,
            'center_freq_mhz': center_freq_hz / 1e6,
            'span_hz': span_hz,
            'span_mhz': span_hz / 1e6,
            'num_bins': num_bins,
            'freq_resolution_hz': span_hz / num_bins if num_bins > 0 else 0,
            'freq_resolution_khz': (span_hz / num_bins / 1000) if num_bins > 0 else 0,
            'freq_start_mhz': (center_freq_hz - span_hz / 2) / 1e6,
            'freq_end_mhz': (center_freq_hz + span_hz / 2) / 1e6,
            'trigger_mode': trigger_mode,
            'repeat_period_ms': repeat_period_ms,
            'freerun_duration_ms': freerun_duration_ms,
            'trigger_count': trigger_count
        }
    }


def get_limits_summary() -> Dict[str, any]:
    """
    Get a summary of all E6000 UTSC limits.
    
    Returns:
        Dict with limit information
    """
    return {
        'frequency': {
            'min_center_freq_mhz': LIMITS.MIN_CENTER_FREQ_HZ / 1e6,
            'max_center_freq_mhz': LIMITS.MAX_CENTER_FREQ_HZ / 1e6,
            'default_center_freq_mhz': LIMITS.DEFAULT_CENTER_FREQ_HZ / 1e6,
        },
        'span': {
            'min_span_mhz': LIMITS.MIN_SPAN_HZ / 1e6,
            'max_span_mhz': LIMITS.MAX_SPAN_HZ / 1e6,
            'default_span_mhz': LIMITS.DEFAULT_SPAN_HZ / 1e6,
            'supported_spans_mhz': [s / 1e6 for s in LIMITS.SUPPORTED_SPANS_HZ],
        },
        'bins': {
            'min_num_bins': LIMITS.MIN_NUM_BINS,
            'max_num_bins': LIMITS.MAX_NUM_BINS,
            'default_num_bins': LIMITS.DEFAULT_NUM_BINS,
            'supported_bin_counts': LIMITS.SUPPORTED_BIN_COUNTS,
        },
        'timing': {
            'min_repeat_period_ms': LIMITS.MIN_REPEAT_PERIOD_MS,
            'max_repeat_period_ms': LIMITS.MAX_REPEAT_PERIOD_MS,
            'default_repeat_period_ms': LIMITS.DEFAULT_REPEAT_PERIOD_MS,
            'min_freerun_duration_ms': LIMITS.MIN_FREERUN_DURATION_MS,
            'max_freerun_duration_ms': LIMITS.MAX_FREERUN_DURATION_MS,
            'default_freerun_duration_ms': LIMITS.DEFAULT_FREERUN_DURATION_MS,
        },
        'trigger': {
            'min_trigger_count': LIMITS.MIN_TRIGGER_COUNT,
            'max_trigger_count': LIMITS.MAX_TRIGGER_COUNT,
            'default_trigger_count': LIMITS.DEFAULT_TRIGGER_COUNT,
        },
        'notes': {
            'e6000_limitations': [
                "Repeat period maximum: 1000ms (1 second) - E6000 hardware limit",
                "Trigger count maximum: 10 captures - E6000 hardware limit",
                "FreeRunning mode uses freerun_duration, not trigger_count",
                "Frequency range: 5-200 MHz (DOCSIS 3.0: 5-85 MHz typical)"
            ]
        }
    }
