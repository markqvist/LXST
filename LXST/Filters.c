#include <math.h>

void highpass_filter(float* input, float* output, int samples, int channels, float alpha, float* filter_states, float* last_inputs) {
  int i, ch;    
  for (ch = 0; ch < channels; ch++) { float input_diff = input[ch] - last_inputs[ch]; output[ch] = alpha * (filter_states[ch] + input_diff); }
  for (i = 1; i < samples; i++) { for (ch = 0; ch < channels; ch++) { int idx = i * channels + ch; float input_diff = input[idx] - input[idx - channels]; output[idx] = alpha * (output[idx - channels] + input_diff); } }
  for (ch = 0; ch < channels; ch++) { int last_idx = (samples - 1) * channels + ch; filter_states[ch] = output[last_idx]; last_inputs[ch] = input[last_idx]; }
}

void lowpass_filter(float* input, float* output, int samples, int channels, float alpha, float* filter_states) {
  int i, ch;
  float one_minus_alpha = 1.0f - alpha;
  for (ch = 0; ch < channels; ch++) { output[ch] = alpha * input[ch] + one_minus_alpha * filter_states[ch]; }
    for (i = 1; i < samples; i++) {
      for (ch = 0; ch < channels; ch++) { int idx = i * channels + ch; output[idx] = alpha * input[idx] + one_minus_alpha * output[idx - channels]; }
    }
  for (ch = 0; ch < channels; ch++) { int last_idx = (samples - 1) * channels + ch; filter_states[ch] = output[last_idx]; }
}

void agc_process(float* input, float* output, int samples, int channels, float target_linear, float max_gain_linear, float trigger_level,
  float attack_coeff, float release_coeff, float hold_samples, float* current_gain_lin, int* hold_counter, int block_target) {

  for (int i = 0; i < samples * channels; i++) { output[i] = input[i]; }
  int num_blocks = block_target;
  int block_size = samples / num_blocks;
  if (block_size < 1) block_size = 1;

  for (int block = 0; block < num_blocks; block++) {
    int                            block_start = block*block_size;
    int                            block_end   = (block + 1)*block_size;
    if (block == num_blocks - 1) { block_end   = samples; }
    if (block_end > samples)     { block_end   = samples; }

    int block_samples = block_end - block_start;
    if (block_samples <= 0) continue;

    for (int ch = 0; ch < channels; ch++) {
      float sum_squares = 0.0f;
      for (int i = block_start; i < block_end; i++) { int idx = i * channels + ch; sum_squares += output[idx] * output[idx]; }
        float rms = sqrtf(sum_squares / block_samples);

      float target_gain;
      if (rms > 1e-9f && rms > trigger_level) {
        target_gain = target_linear / rms;
        if (target_gain > max_gain_linear) { target_gain = max_gain_linear; }
      } else { target_gain = current_gain_lin[ch]; }

      if (target_gain < current_gain_lin[ch]) {
        current_gain_lin[ch] = attack_coeff * target_gain + (1.0f - attack_coeff) * current_gain_lin[ch];
        *hold_counter = (int)hold_samples;
      } else {
        if (*hold_counter > 0) { *hold_counter -= block_samples; }
        else { current_gain_lin[ch] = release_coeff * target_gain + (1.0f - release_coeff) * current_gain_lin[ch]; }
      }

      for (int i = block_start; i < block_end; i++) { int idx = i * channels + ch; output[idx] *= current_gain_lin[ch]; }
    }
  }

  float peak_limit = 0.75f;
  for (int ch = 0; ch < channels; ch++) {
    float peak = 0.0f;
    for (int i = 0; i < samples; i++) { int idx = i * channels + ch; float abs_val = fabsf(output[idx]);
                                        if (abs_val > peak) { peak = abs_val; } }
    
    if (peak > peak_limit) { float scale = peak_limit / peak;
                             for (int i = 0; i < samples; i++) { int idx = i * channels + ch; output[idx] *= scale; } }
  }
}