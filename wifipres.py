#!/usr/bin/env python3
"""
TITAN Human Detection Engine v3.0
Advanced WiFi-based motion detection with multi-metric analysis
Production-Grade Implementation
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.gridspec import GridSpec
from scipy.signal import butter, filtfilt, iirnotch, medfilt, welch, savgol_filter
from scipy.fftpack import fft, fftfreq
from scipy.ndimage import gaussian_filter1d
import subprocess
import threading
import time
import queue
import collections
import sys
import json
import logging
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =============================================================================
# ENUMS & DATA STRUCTURES
# =============================================================================
class DetectionState(Enum):
    CLEAR = 0
    DETECTING = 1
    CONFIRMED = 2

@dataclass
class DetectionEvent:
    timestamp: float
    confidence: float
    rssi: float
    detection_type: str
    
    def to_dict(self):
        return asdict(self)

# =============================================================================
# SYSTEM CONFIGURATION
# =============================================================================
@dataclass
class SystemConfig:
    interface: str = "wlan0"
    sampling_rate: int = 35
    buffer_size: int = 400
    notch_freq: float = 0.5  # Normalized frequency (must be 0 < w0 < 1)
    notch_q: float = 30.0
    bandpass_low: float = 0.4
    bandpass_high: float = 5.5
    bandpass_order: int = 4
    confidence_threshold: float = 0.35
    rise_threshold: float = 0.2
    fall_threshold: float = 0.1
    noise_percentile: int = 25
    max_queue_size: int = 500
    visualization_update_ms: int = 30
    enable_logging: bool = True
    log_file: str = "/tmp/titan_detections.log"
    
    def to_dict(self):
        return asdict(self)

# =============================================================================
# SYSTEM OBFUSCATION & CONSTANTS
# =============================================================================
_0xDATA = ["wlan0", "signal", "iw dev ", " link", "utf-8"]
_HW_CMD = lambda: subprocess.check_output(_0xDATA[2] + _0xDATA[0] + _0xDATA[3], 
                  shell=True, stderr=subprocess.STDOUT).decode(_0xDATA[4])

# =============================================================================
# BULK CLASS: SYSTEM MONITORING & SIGNAL INTEGRITY
# =============================================================================
class SystemHealth:
    """Advanced system health monitoring with multi-factor analysis."""
    def __init__(self, config: SystemConfig):
        self.config = config
        self.packets = collections.deque(maxlen=300)
        self.health_score = 100.0
        self.uptime_counter = 0
        self.error_count = 0
        self.recovery_count = 0
        self.last_packet_time = time.time()
        self.packet_loss_rate = 0.0

    def heart_beat(self):
        now = time.time()
        variance = 0
        
        if len(self.packets) > 15:
            deltas = [self.packets[i] - self.packets[i-1] for i in range(1, len(self.packets))]
            variance = np.std(deltas)
            mean_delta = np.mean(deltas)
            expected_delta = 1.0 / self.config.sampling_rate
            
            # Adaptive health scoring
            if variance > self.config.jitter_thresh if hasattr(self.config, 'jitter_thresh') else 0.06:
                self.health_score -= 0.3
            else:
                self.health_score += 0.12
            
            # Packet loss detection
            if mean_delta > expected_delta * 1.5:
                self.packet_loss_rate = (mean_delta - expected_delta) / expected_delta
                self.health_score -= self.packet_loss_rate * 2
        
        self.packets.append(now)
        self.health_score = np.clip(self.health_score, 0, 100)
        self.uptime_counter += 1
        self.last_packet_time = now
        
        return self.health_score
    
    def record_error(self):
        self.error_count += 1
        self.health_score = np.clip(self.health_score - 1.0, 0, 100)
    
    def record_recovery(self):
        self.recovery_count += 1
        self.health_score = np.clip(self.health_score + 0.5, 0, 100)
    
    def get_uptime_seconds(self):
        return self.uptime_counter / self.config.sampling_rate
    
    def get_health_report(self):
        return {
            'score': self.health_score,
            'uptime_sec': self.get_uptime_seconds(),
            'errors': self.error_count,
            'recoveries': self.recovery_count,
            'packet_loss_rate': self.packet_loss_rate
        }

class AdaptiveNoiseEstimator:
    """Continuously estimates noise floor with adaptive confidence bounds."""
    def __init__(self, config: SystemConfig):
        self.config = config
        self.window_size = 200
        self.noise_buffer = collections.deque(maxlen=self.window_size)
        self.noise_floor = -60.0
        self.noise_std = 1.0
        self.noise_min = -100.0
        self.noise_max = -20.0
        self.confidence_level = 0.5
        
    def update(self, rssi_value):
        self.noise_buffer.append(rssi_value)
        
        if len(self.noise_buffer) >= 40:
            # Multi-percentile approach for robust estimation
            p10 = np.percentile(self.noise_buffer, 10)
            p25 = np.percentile(self.noise_buffer, 25)
            p50 = np.percentile(self.noise_buffer, 50)
            
            # Weighted combination favoring lower percentiles (actual noise)
            self.noise_floor = 0.5 * p25 + 0.3 * p10 + 0.2 * p50
            
            # Calculate robust standard deviation (IQR-based)
            q1 = np.percentile(self.noise_buffer, 25)
            q3 = np.percentile(self.noise_buffer, 75)
            self.noise_std = (q3 - q1) / 1.35
            
            # Confidence increases with buffer size
            self.confidence_level = min(len(self.noise_buffer) / self.window_size, 1.0)
        
        return self.noise_floor, self.noise_std
    
    def get_floor(self):
        return self.noise_floor, self.noise_std
    
    def get_confidence(self):
        return self.confidence_level

class EntityPersistence:
    """Enhanced temporal buffer with hysteresis and decay."""
    def __init__(self, config: SystemConfig):
        self.config = config
        self.memory = np.zeros(30)
        self.active = False
        self.rise_threshold = config.rise_threshold
        self.fall_threshold = config.fall_threshold
        self.last_transition_time = time.time()
        self.state_duration = 0.0
        
    def process(self, trigger):
        self.memory = np.roll(self.memory, -1)
        self.memory[-1] = 1.0 if trigger else 0.0
        confidence = np.mean(self.memory)
        
        # Hysteresis logic with time-based stability
        old_active = self.active
        
        if not self.active and confidence > self.rise_threshold:
            self.active = True
        elif self.active and confidence < self.fall_threshold:
            self.active = False
        
        if self.active != old_active:
            self.last_transition_time = time.time()
            self.state_duration = 0.0
        else:
            self.state_duration = time.time() - self.last_transition_time
        
        return self.active, confidence, self.state_duration

# =============================================================================
# BULK CLASS: SIGNAL PROCESSING ENGINE (ADVANCED)
# =============================================================================
class SignalCore:
    """Advanced multi-stage signal processing with spectral analysis."""
    def __init__(self, config: SystemConfig):
        self.config = config
        self.fs = config.sampling_rate
        self.nyq = 0.5 * self.fs
        
        # Notch filter for interference (normalized frequency must be 0 < w0 < 1)
        # w0 is normalized frequency relative to Nyquist frequency
        notch_w0 = np.clip(config.notch_freq, 0.01, 0.99)
        self.b_n, self.a_n = iirnotch(notch_w0, config.notch_q, 1)
        
        # Multi-stage bandpass design
        self.b_p, self.a_p = butter(config.bandpass_order, 
                                     [config.bandpass_low/self.nyq, 
                                      config.bandpass_high/self.nyq], btype='band')
        
        # High-pass for baseline removal
        self.b_hp, self.a_hp = butter(2, 0.1/self.nyq, btype='high')
        
        # Smoothing filter
        self.b_smooth, self.a_smooth = butter(2, 0.2/self.nyq, btype='low')
        
        # Spectral analysis buffers
        self.spectral_buffer = collections.deque(maxlen=100)
        self.energy_buffer = collections.deque(maxlen=50)
        
        # Adaptive parameters
        self.signal_history = collections.deque(maxlen=500)

    def sanitize(self, raw_buffer):
        """Multi-stage signal conditioning with noise reduction."""
        if len(raw_buffer) < 40: 
            return raw_buffer
        
        # Stage 1: Aggressive median filtering
        denoised = medfilt(raw_buffer, kernel_size=7)
        
        # Stage 2: Remove DC offset
        centered = denoised - np.mean(denoised)
        
        # Stage 3: 60Hz notch filter
        notched = filtfilt(self.b_n, self.a_n, centered)
        
        # Stage 4: Multi-order bandpass
        bandpassed = filtfilt(self.b_p, self.a_p, notched)
        
        # Stage 5: High-pass filtering
        filtered = filtfilt(self.b_hp, self.a_hp, bandpassed)
        
        # Stage 6: Optional Savitzky-Golay smoothing for stability
        if len(filtered) >= 11:
            filtered = savgol_filter(filtered, window_length=11, polyorder=3)
        
        return filtered
    
    def extract_spectral_features(self, signal_segment):
        """Advanced frequency-domain feature extraction."""
        if len(signal_segment) < 32:
            return {
                'dominant_freq': 0.0,
                'spectral_entropy': 0.0,
                'energy_total': 0.0,
                'energy_low': 0.0,
                'energy_mid': 0.0,
                'energy_high': 0.0,
                'peak_power': 0.0
            }
        
        # Compute FFT with Hanning window
        windowed = signal_segment * np.hanning(len(signal_segment))
        fft_result = np.abs(fft(windowed))
        freqs = fftfreq(len(signal_segment), 1/self.fs)
        freqs = freqs[:len(freqs)//2]
        fft_result = fft_result[:len(fft_result)//2]
        
        # Normalize
        fft_result = fft_result / (np.max(fft_result) + 1e-10)
        
        # Extract frequency bands
        low_band = (freqs > 0.5) & (freqs < 1.5)
        mid_band = (freqs >= 1.5) & (freqs < 3.0)
        high_band = (freqs >= 3.0) & (freqs < 5.5)
        
        energy_total = np.sum(fft_result ** 2)
        energy_low = np.sum(fft_result[low_band] ** 2) / (np.sum(low_band) + 1)
        energy_mid = np.sum(fft_result[mid_band] ** 2) / (np.sum(mid_band) + 1)
        energy_high = np.sum(fft_result[high_band] ** 2) / (np.sum(high_band) + 1)
        
        # Find dominant frequency
        if np.any(low_band):
            dominant_idx = np.argmax(fft_result[low_band])
            dominant_freq = freqs[low_band][dominant_idx]
        else:
            dominant_freq = 0.0
        
        # Spectral entropy (normalized)
        normalized_power = fft_result ** 2 / (energy_total + 1e-10)
        spectral_entropy = -np.sum(normalized_power * np.log2(normalized_power + 1e-10))
        
        # Peak power
        peak_power = np.max(fft_result)
        
        return {
            'dominant_freq': float(dominant_freq),
            'spectral_entropy': float(spectral_entropy),
            'energy_total': float(energy_total),
            'energy_low': float(energy_low),
            'energy_mid': float(energy_mid),
            'energy_high': float(energy_high),
            'peak_power': float(peak_power)
        }
    
    def compute_temporal_features(self, signal_segment):
        """Extract time-domain features for motion detection."""
        if len(signal_segment) < 20:
            return {}
        
        features = {}
        
        # Energy features
        features['rms_energy'] = float(np.sqrt(np.mean(signal_segment ** 2)))
        features['peak_amplitude'] = float(np.max(np.abs(signal_segment)))
        features['mean_absolute_value'] = float(np.mean(np.abs(signal_segment)))
        
        # Variability features
        features['variance'] = float(np.var(signal_segment))
        features['std_dev'] = float(np.std(signal_segment))
        
        # Zero-crossing rate
        zero_crossings = np.sum(np.abs(np.diff(np.sign(signal_segment))))
        features['zero_crossing_rate'] = float(zero_crossings / len(signal_segment))
        
        # Kurtosis (peakiness indicator)
        mean_val = np.mean(signal_segment)
        std_val = np.std(signal_segment)
        if std_val > 0:
            kurtosis = np.mean(((signal_segment - mean_val) / std_val) ** 4)
            features['kurtosis'] = float(kurtosis)
        else:
            features['kurtosis'] = 0.0
        
        # Crest factor (peak to RMS ratio)
        if features['rms_energy'] > 0:
            features['crest_factor'] = float(features['peak_amplitude'] / features['rms_energy'])
        else:
            features['crest_factor'] = 1.0
        
        return features
    
    def compute_multi_metric_confidence(self, filtered_signal, raw_signal, noise_floor, noise_std):
        """Advanced confidence computation using multiple orthogonal metrics."""
        if len(filtered_signal) < 40:
            return 0.0, {}
        
        recent_window = filtered_signal[-40:]
        
        # Extract all features
        temporal_features = self.compute_temporal_features(recent_window)
        spectral_features = self.extract_spectral_features(recent_window)
        
        # Metric 1: Energy Detection (0.35 weight)
        energy = temporal_features.get('rms_energy', 0)
        energy_threshold = noise_std * 2.2
        if energy_threshold > 0:
            energy_metric = np.clip(energy / energy_threshold, 0, 1)
        else:
            energy_metric = 0
        
        # Metric 2: Peak-to-Average Ratio (0.20 weight)
        peak_val = temporal_features.get('peak_amplitude', 0)
        if energy > 0.001:
            peak_metric = np.clip((peak_val / energy) / 3.0, 0, 1)
        else:
            peak_metric = 0
        
        # Metric 3: Spectral Concentration (0.20 weight)
        energy_total = spectral_features.get('energy_total', 0.001)
        energy_low = spectral_features.get('energy_low', 0)
        spectral_metric = np.clip(energy_low / (energy_total + 0.001), 0, 1)
        
        # Metric 4: Zero-Crossing Rate (0.15 weight)
        zcr = temporal_features.get('zero_crossing_rate', 0)
        zcr_metric = np.clip(zcr / 0.3, 0, 1)
        
        # Metric 5: Kurtosis (0.10 weight) - peakiness indicates real signal
        kurtosis = temporal_features.get('kurtosis', 3.0)
        kurtosis_metric = np.clip((kurtosis - 3.0) / 4.0, 0, 1)
        
        # Weighted combination
        confidence = (
            0.35 * energy_metric +
            0.20 * peak_metric +
            0.20 * spectral_metric +
            0.15 * zcr_metric +
            0.10 * kurtosis_metric
        )
        
        features_dict = {
            **temporal_features,
            **spectral_features,
            'energy_metric': energy_metric,
            'peak_metric': peak_metric,
            'spectral_metric': spectral_metric,
            'zcr_metric': zcr_metric,
            'kurtosis_metric': kurtosis_metric
        }
        
        return np.clip(confidence, 0, 1), features_dict

# =============================================================================
# MAIN TITAN VISUALIZER (PRODUCTION GRADE)
# =============================================================================
class TitanEngine:
    """Production-grade human detection engine with advanced visualization."""
    
    def __init__(self, config: SystemConfig = None):
        self.config = config or SystemConfig()
        self.buffer = np.full(self.config.buffer_size, -60.0)
        self.q = queue.Queue(maxsize=self.config.max_queue_size)
        self.running = True
        
        # Core modules
        self.core = SignalCore(self.config)
        self.health = SystemHealth(self.config)
        self.persistence = EntityPersistence(self.config)
        self.noise_estimator = AdaptiveNoiseEstimator(self.config)
        
        # Advanced statistics tracking
        self.detection_stats = {
            'total_samples': 0,
            'detections': 0,
            'detection_rate': 0.0,
            'avg_confidence': 0.0,
            'max_confidence': 0.0,
            'min_rssi': 0.0,
            'max_rssi': 0.0,
            'events': []
        }
        
        self.confidence_history = collections.deque(maxlen=200)
        self.rssi_history = collections.deque(maxlen=200)
        self.detection_history = collections.deque(maxlen=300)
        
        # Visualization setup
        self.setup_matplotlib()
        
        # Thread management
        self.harvester_thread = threading.Thread(target=self._harvester, daemon=True)
        self.harvester_thread.start()
        
        logger.info(f"TITAN Engine initialized: {self.config.interface} @ {self.config.sampling_rate}Hz")

    def setup_matplotlib(self):
        """Setup advanced multi-panel visualization."""
        plt.style.use('dark_background')
        self.fig = plt.figure(figsize=(18, 10), facecolor='#0a0e27')
        self.gs = GridSpec(3, 3, figure=self.fig, hspace=0.35, wspace=0.3)
        
        # Main 3D plot
        self.ax_3d = self.fig.add_subplot(self.gs[0:2, 0:2], projection='3d', facecolor='#0a0e27')
        self.ax_3d.set_facecolor('#0a0e27')
        
        # Signal waveform
        self.ax_signal = self.fig.add_subplot(self.gs[0, 2], facecolor='#1a1f3a')
        self.ax_signal.set_title('Filtered Signal', color='#00FFCC', fontsize=10, fontweight='bold')
        
        # Frequency spectrum
        self.ax_fft = self.fig.add_subplot(self.gs[1, 2], facecolor='#1a1f3a')
        self.ax_fft.set_title('Spectrum', color='#00FFCC', fontsize=10, fontweight='bold')
        
        # Confidence history
        self.ax_conf = self.fig.add_subplot(self.gs[2, 0], facecolor='#1a1f3a')
        self.ax_conf.set_title('Confidence Trend', color='#00FFCC', fontsize=10, fontweight='bold')
        self.ax_conf.set_ylabel('Confidence', color='#00FF00', fontsize=9)
        self.ax_conf.tick_params(colors='#00FF00', labelsize=8)
        
        # RSSI history
        self.ax_rssi = self.fig.add_subplot(self.gs[2, 1], facecolor='#1a1f3a')
        self.ax_rssi.set_title('RSSI Level', color='#00FFCC', fontsize=10, fontweight='bold')
        self.ax_rssi.set_ylabel('RSSI (dBm)', color='#FF6600', fontsize=9)
        self.ax_rssi.tick_params(colors='#FF6600', labelsize=8)
        
        # Statistics panel
        self.ax_stats = self.fig.add_subplot(self.gs[2, 2], facecolor='#1a1f3a')
        self.ax_stats.axis('off')

    def _harvester(self):
        """Hardware data acquisition thread with robust error handling."""
        retry_count = 0
        max_retries = 10
        consecutive_errors = 0
        max_consecutive_errors = 20
        
        while self.running:
            try:
                raw = _HW_CMD()
                for line in raw.split('\n'):
                    if _0xDATA[1] in line:
                        try:
                            rssi = int(line.split()[1])
                            if -100 <= rssi <= -20:
                                if not self.q.full(): 
                                    self.q.put(rssi)
                                retry_count = 0
                                consecutive_errors = 0
                                self.health.record_recovery()
                        except (ValueError, IndexError):
                            consecutive_errors += 1
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"Hardware connection critical: {e}")
                    self.health.record_error()
                    consecutive_errors = 0
            
            time.sleep(1 / self.config.sampling_rate)

    def _render_entity_advanced(self, intensity, state_duration):
        """Advanced 3D entity rendering with motion indication."""
        pts = int(np.clip(intensity * 250, 150, 2000))
        
        # Dynamic coloring based on detection duration
        if state_duration < 2.0:
            base_color = '#FF00FF'  # Magenta - new detection
        elif state_duration < 10.0:
            base_color = '#FF0000'  # Red - active detection
        else:
            base_color = '#FF6600'  # Orange - sustained detection
        
        # Torso (60% of points)
        z_t = np.random.normal(7, 2.0, int(pts * 0.60))
        y_t = np.random.normal(0, 1.4, int(pts * 0.60))
        x_t = np.random.normal(self.config.buffer_size - 15, 0.9, int(pts * 0.60))
        
        # Head (25% of points)
        z_h = np.random.normal(12, 0.5, int(pts * 0.25))
        y_h = np.random.normal(0, 0.4, int(pts * 0.25))
        x_h = np.random.normal(self.config.buffer_size - 15, 0.3, int(pts * 0.25))
        
        # Limbs/Motion trails (15% of points)
        z_l = np.random.normal(6, 3.5, int(pts * 0.15))
        y_l = np.random.normal(0, 3.5, int(pts * 0.15))
        x_l = np.random.normal(self.config.buffer_size - 15, 2.2, int(pts * 0.15))
        
        # Glow effect with intensity
        glow_intensity = int(50 + intensity * 200)
        
        # Render with depth perception
        self.ax_3d.scatter(x_t, y_t, z_t, c=base_color, s=intensity*3, 
                          alpha=0.5, depthshade=True, edgecolors='white', linewidth=0.5)
        self.ax_3d.scatter(x_h, y_h, z_h, c='white', s=intensity*3, alpha=0.7, 
                          depthshade=True, edgecolors='yellow', linewidth=0.5)
        self.ax_3d.scatter(x_l, y_l, z_l, c='cyan', s=intensity*1.5, alpha=0.4, 
                          depthshade=True, edgecolors='#00FFFF', linewidth=0.3)

    def _update(self, frame):
        """Advanced main update loop with comprehensive visualization."""
        # Data collection
        while not self.q.empty():
            try:
                rssi = self.q.get(timeout=0.01)
                self.buffer = np.roll(self.buffer, -1)
                self.buffer[-1] = rssi
                self.health.heart_beat()
                self.noise_estimator.update(rssi)
                self.rssi_history.append(rssi)
            except queue.Empty:
                break

        # Signal processing
        filtered = self.core.sanitize(self.buffer)
        noise_floor, noise_std = self.noise_estimator.get_floor()
        
        # Enhanced detection with feature extraction
        confidence, features = self.core.compute_multi_metric_confidence(
            filtered, self.buffer, noise_floor, noise_std
        )
        
        # State machine
        active, persistence_confidence, state_duration = self.persistence.process(
            confidence > self.config.confidence_threshold
        )
        
        # Display confidence (blend instantaneous and persistence)
        display_confidence = max(confidence, persistence_confidence * 0.75)
        
        # Statistics update
        self.detection_stats['total_samples'] += 1
        if active:
            self.detection_stats['detections'] += 1
        
        self.confidence_history.append(confidence)
        self.detection_stats['detection_rate'] = (
            self.detection_stats['detections'] / 
            max(self.detection_stats['total_samples'], 1)
        ) * 100
        self.detection_stats['avg_confidence'] = np.mean(self.confidence_history)
        self.detection_stats['max_confidence'] = max(self.confidence_history)
        
        if len(self.rssi_history) > 0:
            self.detection_stats['min_rssi'] = min(self.rssi_history)
            self.detection_stats['max_rssi'] = max(self.rssi_history)

        # 3D Visualization
        self.ax_3d.cla()
        self.ax_3d.set_axis_off()
        self.ax_3d.set_xlim(0, self.config.buffer_size)
        self.ax_3d.set_ylim(-18, 18)
        self.ax_3d.set_zlim(0, 22)
        
        # Signal trace on ground
        t_x = np.arange(len(filtered))
        scaled_signal = filtered * 3.5
        self.ax_3d.plot(t_x, scaled_signal, zs=0, zdir='z', color='#00FFCC', alpha=0.6, lw=2)
        
        # Noise floor reference
        noise_visual = np.full_like(t_x, noise_floor / 13, dtype=float)
        self.ax_3d.plot(t_x, noise_visual, zs=0, zdir='z', color='#FF6600', alpha=0.4, 
                       lw=1.5, linestyle='--')
        
        # 3D entity rendering
        if active:
            self._render_entity_advanced(display_confidence, state_duration)
        
        # Status header
        if active:
            status_text = f"◆ HUMAN DETECTED ◆"
            status_color = '#FF0000'
        else:
            status_text = f"○ SYSTEM CLEAR ○"
            status_color = '#00FFCC'
        
        self.ax_3d.text2D(0.5, 0.98, status_text, transform=self.ax_3d.transAxes, 
                         color=status_color, fontweight='bold', fontsize=14, 
                         ha='center', family='monospace',
                         bbox=dict(boxstyle='round,pad=0.5', facecolor='#0a0e27', 
                                  edgecolor=status_color, linewidth=2))
        
        # Detailed status
        conf_text = f"CONF: {display_confidence:.1%} | RATE: {self.detection_stats['detection_rate']:.1f}%"
        self.ax_3d.text2D(0.5, 0.92, conf_text, transform=self.ax_3d.transAxes, 
                         color='#FFFF00', fontsize=10, ha='center', family='monospace')
        
        # Signal waveform plot
        self.ax_signal.clear()
        self.ax_signal.plot(filtered[-100:], color='#00FFCC', linewidth=1.5, alpha=0.8)
        self.ax_signal.fill_between(range(len(filtered[-100:])), filtered[-100:], alpha=0.2, color='#00FFCC')
        self.ax_signal.set_facecolor('#1a1f3a')
        self.ax_signal.grid(True, alpha=0.2, color='#00FFCC')
        self.ax_signal.tick_params(colors='#00FF00', labelsize=8)
        
        # FFT spectrum
        self.ax_fft.clear()
        if len(filtered) >= 64:
            fft_result = np.abs(fft(filtered[-64:]))[:32]
            freqs = fftfreq(64, 1/self.config.sampling_rate)[:32]
            self.ax_fft.bar(freqs, fft_result, color='#FF6600', alpha=0.7, width=0.1)
        self.ax_fft.set_facecolor('#1a1f3a')
        self.ax_fft.set_xlim(0, 6)
        self.ax_fft.tick_params(colors='#FF6600', labelsize=8)
        self.ax_fft.grid(True, alpha=0.2, color='#FF6600')
        
        # Confidence history
        self.ax_conf.clear()
        if len(self.confidence_history) > 0:
            self.ax_conf.plot(list(self.confidence_history), color='#FFFF00', linewidth=1.5)
            self.ax_conf.fill_between(range(len(self.confidence_history)), 
                                      list(self.confidence_history), alpha=0.3, color='#FFFF00')
            self.ax_conf.axhline(y=self.config.confidence_threshold, color='#FF0000', 
                                linestyle='--', alpha=0.5, linewidth=1)
        self.ax_conf.set_facecolor('#1a1f3a')
        self.ax_conf.set_ylim(0, 1)
        self.ax_conf.tick_params(colors='#00FF00', labelsize=8)
        self.ax_conf.grid(True, alpha=0.2, color='#00FF00')
        
        # RSSI history
        self.ax_rssi.clear()
        if len(self.rssi_history) > 0:
            self.ax_rssi.plot(list(self.rssi_history), color='#FF6600', linewidth=1.5)
            self.ax_rssi.fill_between(range(len(self.rssi_history)), 
                                      list(self.rssi_history), alpha=0.2, color='#FF6600')
            self.ax_rssi.axhline(y=noise_floor, color='#00FFCC', linestyle='--', alpha=0.5, linewidth=1)
        self.ax_rssi.set_facecolor('#1a1f3a')
        self.ax_rssi.tick_params(colors='#FF6600', labelsize=8)
        self.ax_rssi.grid(True, alpha=0.2, color='#FF6600')
        
        # Statistics panel
        self.ax_stats.clear()
        self.ax_stats.axis('off')
        
        stats_text = (
            f"┌─ SYSTEM STATS ─┐\n"
            f"│ Samples: {self.detection_stats['total_samples']:,}\n"
            f"│ Detections: {self.detection_stats['detections']:,}\n"
            f"│ Avg Conf: {self.detection_stats['avg_confidence']:.2f}\n"
            f"│ Max Conf: {self.detection_stats['max_confidence']:.2f}\n"
            f"│ RSSI: {self.buffer[-1]:.0f} dBm\n"
            f"│ Noise: {noise_floor:.1f} ± {noise_std:.2f}\n"
            f"│ Health: {self.health.health_score:.0f}%\n"
            f"└─────────────────┘"
        )
        
        self.ax_stats.text(0.05, 0.95, stats_text, transform=self.ax_stats.transAxes, 
                          color='#00FF00', fontsize=9, family='monospace', 
                          verticalalignment='top', bbox=dict(boxstyle='round', 
                          facecolor='#0a0e27', alpha=0.8, edgecolor='#00FF00', linewidth=1))

    def start(self):
        """Start the detection engine with visualization."""
        logger.info("=" * 60)
        logger.info("TITAN ENGINE v3.0 - PRODUCTION GRADE HUMAN DETECTION")
        logger.info("=" * 60)
        logger.info(f"Interface: {self.config.interface}")
        logger.info(f"Sampling Rate: {self.config.sampling_rate} Hz")
        logger.info(f"Buffer Size: {self.config.buffer_size} samples")
        logger.info(f"Detection Algorithm: Advanced Multi-Metric with Spectral Analysis")
        logger.info(f"Confidence Threshold: {self.config.confidence_threshold}")
        logger.info("=" * 60)
        
        ani = FuncAnimation(self.fig, self._update, interval=self.config.visualization_update_ms, 
                          cache_frame_data=False, repeat=True)
        plt.show()

    def save_statistics(self, filepath="/tmp/titan_stats.json"):
        """Save session statistics to file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(self.detection_stats, f, indent=2)
            logger.info(f"Statistics saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save statistics: {e}")

    def stop(self):
        """Gracefully shutdown the engine."""
        self.running = False
        self.save_statistics()
        logger.info("TITAN Engine shutdown complete")

if __name__ == "__main__":
    try:
        engine = TitanEngine()
        engine.start()
    except KeyboardInterrupt:
        logger.info("\n[SHUTDOWN] System offline.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Critical error: {e}")
        sys.exit(1)
