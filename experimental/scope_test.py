from archive.pico_scope import PicoScope

def generate_test_data(frequency_hz=50, duration_ms=100, amplitude_mv=1000, offset_mv=1650):
    """Generate fake oscilloscope data - sine wave"""
    samples = []
    timestamps = []
    
    # Calculate sample period (aiming for ~10kHz sampling)
    sample_period_us = 100  # 100 microseconds = 10kHz
    num_samples = (duration_ms * 1000) // sample_period_us
    
    for i in range(num_samples):
        t_us = i * sample_period_us
        t_s = t_us / 1_000_000
        
        # Generate sine wave
        mv = offset_mv + amplitude_mv * math.sin(2 * math.pi * frequency_hz * t_s)
        mv = int(max(0, min(3300, mv)))  # Clamp to ADC range
        
        samples.append(mv)
        timestamps.append(t_us)
    
    return samples, timestamps

p = PicoScope()
p.millivolts_list, p.rel_us_list = generate_test_data(frequency_hz=30, duration_ms=100)
p.pico_before_post_ns = utime.time() * 1_000_000_000  # Convert to nanoseconds

p.post_scope_data()