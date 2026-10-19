# Audio third-party notices

The StreamingVAD boundary adapter in avoidance/audio_analysis.py follows faster-whisper no-pad voice segmentation. faster-whisper and its model conversion are MIT licensed. Its notice is reproduced below. The optional installer obtains dependency distributions with their own notices; they are not vendored into this source release.

MIT License

Copyright (c) 2023 SYSTRAN

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


Silero voice model: bundled with faster-whisper; see https://github.com/snakers4/silero-vad (MIT). Whisper model origin: https://github.com/openai/whisper (MIT). Converted model: https://huggingface.co/Systran/faster-whisper-base, pinned in audio_model.source.json.

Included generated WAV files use voices described in recordings/README.md and manifest.json. Piper is a GPL-3.0 development-only generator, not a required runtime dependency or redistributed tool/model. English training dataset is public domain; Spanish model card lists Unlicense.
