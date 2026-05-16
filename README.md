# Vocal Reference Generator

A web application that processes audio files to create AI-compatible vocal references for music production tools like Suno. This tool extracts vocals from songs, applies humming synthesis to destroy phonetic fingerprinting, and provides transpose options to break audio fingerprint detection.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/flask-2.0+-green.svg)

## Features

- **Vocal Separation**: Uses Demucs 4.0.1 to extract clean vocals from mixed audio
- **Humming Synthesis**: Converts vocals to synthetic humming sounds, removing phonetic content that AI systems can fingerprint
- **Transpose Control**: Shift pitch by ±3 semitones to break audio fingerprinting
- **Full Mix Mode**: Optionally include pitch-shifted instrumental track for complete song transformation
- **Real-time Processing**: Web interface with progress tracking
- **Rate Limiting**: Built-in abuse prevention (10 uploads/hour per IP)
- **Optional Password Protection**: Configurable login system
- **Responsive UI**: Teal/cyan gradient theme matching cruzgsworks.space

## Presets

| Preset | Description | Use Case |
|--------|-------------|----------|
| **Default** | Standard vocal extraction | General reference generation |
| **Suno Reference** | Optimized for Suno AI | Creating style references for Suno |
| **Simlish (Humming)** | Heavy humming synthesis | Maximum phonetic destruction |
| **Alien/Gibberish** | Extreme processing | Experimental/creative use |
| **Subtle** | Light processing | Minimal artifact introduction |
| **Vocals Only** | No instrumental track | Clean vocal reference |

## How It Works

1. **Upload**: User uploads an audio file (MP3, WAV, etc.)
2. **Separate**: Demucs splits audio into vocal and instrumental stems
3. **Extract Pitch**: Uses Praat to extract pitch contours from vocals
4. **Synthesize**: Creates synthetic tones following the pitch contour (no phonemes)
5. **Transpose**: Optional pitch shifting to break audio fingerprints
6. **Mix**: Combines processed vocals with optional pitch-shifted instrumental
7. **Download**: User downloads the AI-compatible reference file

## Installation

### Prerequisites

- Python 3.8+
- CUDA-capable GPU (recommended for speed)
- FFmpeg and FFprobe

### Ubuntu/Debian

```bash
# Clone the repository
git clone https://github.com/cruzgsworks/vocal-ref.git
cd vocal-ref

# Install system dependencies
sudo apt update
sudo apt install -y ffmpeg python3-pip python3-venv

# Install Python dependencies
pip install -r requirements.txt

# Run setup script
chmod +x setup.sh
sudo ./setup.sh
```

### Manual Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VOCAL_REF_PASSWORD` | Enable password protection | `None` (disabled) |
| `MAX_UPLOADS_PER_HOUR` | Rate limit per IP | `10` |
| `FLASK_SECRET_KEY` | Session encryption key | Auto-generated |

### Systemd Service

The included `vocal-web.service` file configures the app to run as a systemd service:

```bash
# Copy service file
sudo cp vocal-web.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable vocal-web
sudo systemctl start vocal-web
```

### Apache Reverse Proxy

Example configuration in `apache-proxy.conf`:

```apache
ProxyPreserveHost On
ProxyPass /vocal-ref http://127.0.0.1:5000/vocal-ref
ProxyPassReverse /vocal-ref http://127.0.0.1:5000/vocal-ref
```

## Usage

### Web Interface

1. Navigate to `https://your-domain.com/vocal-ref/`
2. Upload an audio file (max 100MB)
3. Select a preset or customize settings:
   - **Transpose**: -3 to +3 semitones
   - **Mode**: Vocals Only or Full Mix
4. Click "Generate Vocal Reference"
5. Wait for processing (typically 30-90 seconds)
6. Download the result

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main web interface |
| `/api/presets` | GET | Get available presets |
| `/api/upload` | POST | Upload audio file |
| `/api/status/<job_id>` | GET | Check processing status |
| `/api/download/<job_id>` | GET | Download processed file |

### API Example

```bash
# Upload file
curl -X POST -F "audio=@song.mp3" https://your-domain.com/vocal-ref/api/upload

# Check status
curl https://your-domain.com/vocal-ref/api/status/<job_id>

# Download result
curl -O https://your-domain.com/vocal-ref/api/download/<job_id>
```

## Technical Details

### Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│   Client    │────▶│ Flask App   │────▶│  Job Queue      │
│   Browser   │     │   (app.py)  │     │  (in-memory)    │
└─────────────┘     └─────────────┘     └─────────────────┘
                                               │
                                               ▼
                                        ┌─────────────────┐
                                        │  Pipeline       │
                                        │  (pipeline.py)  │
                                        │  • Demucs       │
                                        │  • Praat        │
                                        │  • Synthesis    │
                                        └─────────────────┘
```

### Processing Pipeline

1. **Demucs Separation**: `demucs.pretrained.get_model('htdemucs')`
2. **Audio Conversion**: FFmpeg for format normalization
3. **Pitch Extraction**: Parselmouth (Praat Python bindings)
4. **Humming Synthesis**: Custom synthesis using `torchaudio`
5. **Transpose**: Librosa pitch shifting
6. **Final Mix**: AudioSegment overlay

### Rate Limiting

- Tracks uploads by IP address
- Default: 10 uploads per hour per IP
- Automatic cleanup of expired entries
- Returns HTTP 429 when limit exceeded

## Security Considerations

- **File Validation**: Only accepts audio MIME types
- **Size Limits**: 100MB max upload
- **Sandboxing**: Processing isolated to uploads/outputs directories
- **No Persistent Storage**: Files auto-deleted after 24 hours (job timeout)
- **Session Security**: Flask secure session cookies

## Troubleshooting

### Common Issues

**"FFmpeg/FFprobe not found"**
```bash
sudo apt install ffmpeg
```

**"CUDA out of memory"**
- Reduce batch size or use CPU mode
- Check GPU memory: `nvidia-smi`

**"Rate limit exceeded"**
- Wait 1 hour, or adjust `MAX_UPLOADS_PER_HOUR`

**Processing hangs**
- Check logs: `sudo journalctl -u vocal-web -f`
- Verify Demucs model downloaded: `~/.cache/torch/hub/`

## License

MIT License - see [LICENSE](LICENSE) file for details.

Copyright (c) 2024 cruzgsworks

## Credits

- **Demucs**: Facebook Research - [github.com/facebookresearch/demucs](https://github.com/facebookresearch/demucs)
- **Parselmouth**: Praat Python interface - [github.com/YannickJadoul/Parselmouth](https://github.com/YannickJadoul/Parselmouth)
- **Bootstrap 5**: UI framework - [getbootstrap.com](https://getbootstrap.com)

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Support

For issues and feature requests, please use the [GitHub Issues](https://github.com/cruzgsworks/vocal-ref/issues) page.

---

**Note**: This tool is designed for creating AI-compatible audio references for legitimate music production use. Please respect copyright and only process audio you have rights to use.
