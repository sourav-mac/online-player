# Video Streaming Proxy

A lightweight, production-ready video streaming server that enables instant playback of remote videos without downloading the entire file.

## ✨ Features

- **Instant streaming** with HTTP Range request support
- **Seek/rewind** enabled (if upstream server supports ranges)
- **Smart validation** before streaming starts
- **Recent links** saved in browser
- **Responsive design** mobile-friendly UI
- **Error handling** with detailed feedback
- **Logging** for debugging and monitoring
- **Zero external dependencies** for core functionality

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Server
```bash
python app.py
```

The server starts at: **http://127.0.0.1:5000**

### 3. Use It
- Paste a direct video URL (`.mp4`, `.webm`, `.mkv`, etc.)
- Click **Play**
- Stream instantly! 🎬

## 📋 Test Videos

Try these URLs to test:
- **Short (5s):** https://samplelib.com/lib/preview/mp4/sample-5s.mp4
- **Full HD:** https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4

## 🛠️ How It Works

```
┌─────────────┐        ┌─────────────┐        ┌──────────────┐
│   Browser   │───────→│   Flask App │───────→│  Video URL   │
│  (HTML5)    │        │   (Proxy)   │        │   Source     │
└─────────────┘        └─────────────┘        └──────────────┘
      ↓                      ↓
   Ranges                Forwards Ranges
   Seek/buffer          & Headers
```

### Range Requests
The browser requests specific byte ranges (e.g., `bytes=0-1048576`). Your Flask server:
1. Forwards the Range header to the upstream server
2. Streams only those bytes back to the browser
3. Browser buffers and enables seeking

## 📁 Project Structure

```
video-streamer/
├── app.py                 # Flask server (streaming logic)
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html        # Web UI (responsive, modern)
└── stream.log            # Server logs (auto-generated)
```

## ⚙️ Configuration

Edit these in `app.py`:

```python
CHUNK_SIZE = 1024 * 1024           # Chunk size for streaming (1MB default)
REQUEST_TIMEOUT = (5, 30)          # (connect, read) timeout in seconds
MAX_FILE_SIZE = 10 * 1024**3       # Max file size (10GB default)
```

## 🔒 Security & Best Practices

✅ **Implemented:**
- URL validation (only HTTP/HTTPS)
- Connection timeouts to prevent hangs
- File size limits
- Error handling & logging
- No buffering entire files

⚠️ **Remember:**
- Do NOT use this to stream copyrighted or DRM-protected content
- Rate-limit in production (use Nginx/CloudFlare)
- Run behind HTTPS in production (Let's Encrypt)
- Add authentication if needed

## 🚀 Production Deployment

### Option 1: Gunicorn (Recommended)
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Option 2: Docker
```bash
docker build -t video-streamer .
docker run -p 5000:5000 video-streamer
```

### Option 3: Systemd Service
Create `/etc/systemd/system/video-streamer.service`:
```ini
[Unit]
Description=Video Streaming Proxy
After=network.target

[Service]
Type=notify
User=www-data
WorkingDirectory=/opt/video-streamer
ExecStart=/usr/bin/gunicorn -w 4 -b 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
systemctl enable video-streamer
systemctl start video-streamer
```

## 📊 Performance Tips

1. **Use Gunicorn with multiple workers** for concurrent streams
2. **Add Nginx reverse proxy** for caching & load balancing
3. **Enable gzip compression** in Nginx for metadata
4. **Use CloudFlare/CDN** to cache popular ranges
5. **Monitor with ELK stack** or similar for high-traffic scenarios

## 🐛 Debugging

Check `stream.log` for:
- Connection errors
- Timeout issues
- Validation failures
- Streaming progress

Example:
```
2024-01-13 10:30:45,123 - __main__ - INFO - Stream request for: https://example.com/video.mp4
2024-01-13 10:30:45,456 - __main__ - INFO - Range request: bytes=0-1048575
2024-01-13 10:30:47,789 - __main__ - INFO - Successfully streamed 100 chunks
```

## 📚 API Reference

### `/` - Main Page
Returns the HTML5 video player interface.

### `GET /stream?url=<URL>`
Streams video from remote URL.

**Parameters:**
- `url` (required): Direct video URL

**Query support:**
- Accepts HTTP Range headers from browser
- Returns 206 (Partial Content) for ranges, 200 for full file

**Example:**
```
GET /stream?url=https://example.com/video.mp4
Range: bytes=0-1048575
```

### `GET /api/validate?url=<URL>`
Validates URL and returns metadata.

**Response:**
```json
{
  "valid": true,
  "content_type": "video/mp4",
  "content_length": "52428800",
  "accept_ranges": "bytes",
  "supports_range": true
}
```

## 🎓 Learning Outcomes

By working with this project, you'll learn:
- HTTP Range requests & byte streaming
- Flask request/response handling
- Generator functions for memory efficiency
- HTML5 video controls & API
- URL validation & security
- Error handling & logging
- Production deployment patterns

## ❓ FAQ

**Q: Why does it work with some videos but not others?**
A: The upstream server must support HTTP Range requests (most do). Some CDNs or DRM-protected streams don't.

**Q: Can I use this with YouTube?**
A: No. YouTube uses DASH/HLS streams and DRM. You'd need `yt-dlp` and separate logic.

**Q: Is it legal?**
A: This tool itself is legal. Using it to stream copyrighted content without permission is not. Respect IP.

**Q: How do I add authentication?**
A: Wrap the `/stream` route with Flask-HTTPAuth or similar:
```python
from flask_httpauth import HTTPBasicAuth
auth = HTTPBasicAuth()

@app.route('/stream')
@auth.login_required
def stream():
    ...
```

**Q: Performance for 100+ concurrent users?**
A: Use Gunicorn + Nginx + load balancer. Consider CloudFlare/CDN for popular videos.

## 📄 License

MIT License - free for personal & educational use.

## 🤝 Contributing

Found a bug? Have an idea? Feel free to extend this project with:
- Subtitle support
- Audio-only streaming
- Download progress tracking
- Stream quality selection
- Authentication & ACLs

---

Happy streaming! 🎬
