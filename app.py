"""
Video Streaming Proxy Server
Streams video content from remote URLs with HTTP Range support.
Supports direct streams (MP4), HLS (.m3u8), and quality/audio detection.
"""

from flask import Flask, request, Response, render_template, abort, jsonify
import requests
from urllib.parse import urlparse, urljoin
import logging
from datetime import datetime
import json
import subprocess
import os
import re
try:
    import m3u8
except ImportError:
    m3u8 = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('stream.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Configuration
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
REQUEST_TIMEOUT = (5, 30)  # (connect, read) in seconds
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10GB limit


def is_valid_url(url):
    """Validate URL format and scheme."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https') and parsed.netloc
    except Exception as e:
        logger.warning(f"URL validation error: {e}")
        return False


def is_hls_url(url):
    """Check if URL is an HLS (.m3u8) stream."""
    return url.lower().endswith('.m3u8')


def get_ffprobe_info(url):
    """
    Get video metadata using ffprobe.
    Returns: {streams: [...], format: {...}}
    """
    try:
        # Check if ffprobe is available
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', url],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            logger.warning(f"ffprobe error for {url}: {result.stderr}")
            return None
    except FileNotFoundError:
        logger.warning("ffprobe not found. Install ffmpeg to enable metadata detection.")
        return None
    except Exception as e:
        logger.warning(f"ffprobe exception: {e}")
        return None


def parse_hls_playlist(url):
    """
    Parse HLS (.m3u8) playlist and extract variants.
    Returns: {variants: [...], audio_tracks: [...], subtitles: [...]}
    """
    if not m3u8:
        logger.warning("m3u8 library not available")
        return None
    
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        playlist = m3u8.loads(response.text)
        
        variants = []
        audio_tracks = []
        subtitles = []
        
        # Extract variants (different quality levels)
        if playlist.playlists:
            for variant in playlist.playlists:
                info = {
                    'url': urljoin(url, variant.uri),
                    'bandwidth': variant.stream_info.bandwidth,
                    'resolution': variant.stream_info.resolution,
                    'audio': variant.stream_info.audio,  # Audio group ID
                }
                variants.append(info)
        
        # Extract audio tracks (media playlists)
        if hasattr(playlist, 'media'):
            for media in playlist.media:
                if media.type == 'AUDIO':
                    audio_tracks.append({
                        'language': media.language,
                        'name': media.name,
                        'uri': urljoin(url, media.uri) if media.uri else None,
                        'group_id': media.group_id,
                    })
        
        # Extract subtitle tracks
        if hasattr(playlist, 'media'):
            for media in playlist.media:
                if media.type == 'SUBTITLES':
                    subtitles.append({
                        'language': media.language,
                        'name': media.name,
                        'uri': urljoin(url, media.uri) if media.uri else None,
                    })
        
        # Sort variants by bandwidth
        variants.sort(key=lambda v: v.get('bandwidth', 0) or 0, reverse=True)
        
        return {
            'variants': variants,
            'audio_tracks': audio_tracks,
            'subtitles': subtitles,
            'is_master': len(variants) > 0,
            'master_url': url,
        }
    
    except Exception as e:
        logger.error(f"HLS parsing error for {url}: {e}")
        return None


@app.route('/')
def index():
    """Serve the main page."""
    return render_template('index.html')


@app.route('/api/validate')
def validate():
    """Validate a URL and return metadata (quality, audio, format)."""
    url = request.args.get('url', '').strip()
    
    if not is_valid_url(url):
        return jsonify({'valid': False, 'error': 'Invalid URL format'}), 400
    
    is_hls = is_hls_url(url)
    
    try:
        # For HLS streams
        if is_hls:
            hls_info = parse_hls_playlist(url)
            if hls_info:
                return jsonify({
                    'valid': True,
                    'type': 'hls',
                    'variants': hls_info['variants'],
                    'audio_tracks': hls_info['audio_tracks'],
                    'is_master': hls_info['is_master']
                })
            else:
                return jsonify({'valid': False, 'error': 'Failed to parse HLS playlist'}), 400
        
        # For direct streams (MP4, WebM, etc.)
        resp = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        
        if resp.status_code not in (200, 206):
            return jsonify({
                'valid': False,
                'error': f'Server returned {resp.status_code}'
            }), 400
        
        content_type = resp.headers.get('Content-Type', 'unknown')
        content_length = resp.headers.get('Content-Length', 'unknown')
        accept_ranges = resp.headers.get('Accept-Ranges', 'none')
        
        result = {
            'valid': True,
            'type': 'direct',
            'content_type': content_type,
            'content_length': content_length,
            'accept_ranges': accept_ranges,
            'supports_range': accept_ranges == 'bytes'
        }
        
        # Try to get detailed metadata with ffprobe
        ffprobe_data = get_ffprobe_info(url)
        if ffprobe_data:
            streams = ffprobe_data.get('streams', [])
            
            # Extract video qualities
            video_streams = [s for s in streams if s.get('codec_type') == 'video']
            audio_streams = [s for s in streams if s.get('codec_type') == 'audio']
            
            videos = []
            for v in video_streams:
                videos.append({
                    'width': v.get('width'),
                    'height': v.get('height'),
                    'codec': v.get('codec_name'),
                    'bitrate': v.get('bit_rate'),
                    'fps': eval(v.get('r_frame_rate', '0/1')),
                })
            
            audios = []
            for a in audio_streams:
                audios.append({
                    'language': a.get('tags', {}).get('language', 'unknown'),
                    'codec': a.get('codec_name'),
                    'channels': a.get('channels'),
                    'sample_rate': a.get('sample_rate'),
                })
            
            if videos:
                result['video_streams'] = videos
            if audios:
                result['audio_streams'] = audios
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Validation error for {url}: {e}")
        return jsonify({'valid': False, 'error': str(e)}), 502


@app.route('/stream')
def stream():
    """Stream video from remote URL with Range request support."""
    url = request.args.get('url', '').strip()
    quality = request.args.get('quality')  # For HLS variant selection
    
    # Validate URL
    if not is_valid_url(url):
        logger.warning(f"Invalid URL attempt: {url}")
        abort(400, 'Invalid or missing URL')
    
    logger.info(f"Stream request for: {url}")
    
    # Handle HLS streams
    if is_hls_url(url):
        return stream_hls(url, quality)
    
    # Handle direct streams
    return stream_direct(url)


@app.route('/download')
def download():
    """Download video file from remote URL."""
    url = request.args.get('url', '').strip()
    
    # Validate URL
    if not is_valid_url(url):
        logger.warning(f"Invalid download URL attempt: {url}")
        abort(400, 'Invalid or missing URL')
    
    logger.info(f"Download request for: {url}")
    
    # Don't allow HLS downloads (too complex, would need to merge segments)
    if is_hls_url(url):
        abort(400, 'HLS streams cannot be downloaded directly. Please use a HLS downloader tool.')
    
    try:
        # Fetch the file with streaming enabled
        response = requests.get(
            url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        
        if response.status_code not in (200, 206):
            abort(502, f'Source returned {response.status_code}')
        
        # Check file size
        try:
            content_length = int(response.headers.get('Content-Length', 0))
            if content_length > MAX_FILE_SIZE:
                logger.warning(f"Download file too large: {content_length} bytes")
                abort(413, 'File too large to download')
        except (ValueError, TypeError):
            pass
        
        # Extract filename from URL or use default
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        filename = parsed_url.path.split('/')[-1]
        if not filename or '.' not in filename:
            filename = 'video.mp4'
        
        # Prepare headers for download
        headers = {
            'Content-Type': response.headers.get('Content-Type', 'video/mp4'),
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Cache-Control': 'no-cache',
        }
        
        if 'Content-Length' in response.headers:
            headers['Content-Length'] = response.headers['Content-Length']
        
        def generate_download():
            """Generator to yield chunks for download."""
            try:
                chunk_count = 0
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        chunk_count += 1
                        yield chunk
                logger.info(f"Successfully downloaded {chunk_count} chunks of {filename}")
            except Exception as e:
                logger.error(f"Error during download: {e}")
            finally:
                response.close()
        
        return Response(generate_download(), headers=headers)
    
    except requests.Timeout:
        logger.error(f"Download timeout for {url}")
        abort(504, 'Download source timeout')
    except requests.RequestException as e:
        logger.error(f"Download error for {url}: {e}")
        abort(502, 'Cannot reach download source')


def stream_direct(url):
    """Stream direct video file (MP4, WebM, etc.)."""
    # Prepare headers for upstream request
    upstream_headers = {}
    range_header = request.headers.get('Range')
    if range_header:
        upstream_headers['Range'] = range_header
        logger.info(f"Range request: {range_header}")
    
    try:
        # Fetch from upstream with streaming enabled
        upstream_resp = requests.get(
            url,
            headers=upstream_headers,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        
    except requests.Timeout:
        logger.error(f"Timeout streaming from {url}")
        abort(504, 'Upstream server timeout')
    except requests.RequestException as e:
        logger.error(f"Upstream error for {url}: {e}")
        abort(502, f'Cannot reach video source')
    
    # Check Content-Length doesn't exceed limit
    try:
        content_length = int(upstream_resp.headers.get('Content-Length', 0))
        if content_length > MAX_FILE_SIZE:
            logger.warning(f"File too large: {content_length} bytes")
            abort(413, 'File too large')
    except (ValueError, TypeError):
        pass
    
    # Prepare response headers
    response_headers = {
        'Content-Type': upstream_resp.headers.get('Content-Type', 'application/octet-stream'),
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-cache',
    }
    
    # Forward important headers from upstream
    for header in ['Content-Length', 'Content-Range', 'Content-Disposition']:
        if header in upstream_resp.headers:
            response_headers[header] = upstream_resp.headers[header]
    
    # Determine response status code
    status_code = upstream_resp.status_code if upstream_resp.status_code in (200, 206) else 200
    
    def generate_chunks():
        """Generator to yield chunks from upstream."""
        try:
            chunk_count = 0
            for chunk in upstream_resp.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    chunk_count += 1
                    yield chunk
            logger.info(f"Successfully streamed {chunk_count} chunks")
        except Exception as e:
            logger.error(f"Error during streaming: {e}")
        finally:
            upstream_resp.close()
    
    return Response(generate_chunks(), status=status_code, headers=response_headers)


def stream_hls(url, quality=None):
    """Stream HLS playlist or segments."""
    try:
        # Parse HLS playlist
        hls_info = parse_hls_playlist(url)
        if not hls_info:
            abort(400, 'Failed to parse HLS playlist')
        
        # If master playlist with variants, return selected variant
        if hls_info['is_master'] and hls_info['variants']:
            # Get the requested quality or use the highest quality
            if quality:
                selected = next((v for v in hls_info['variants'] if str(v.get('bandwidth')) == quality), None)
            else:
                selected = hls_info['variants'][0]  # Highest quality by default
            
            if selected:
                # Recursively get the variant playlist
                return stream_hls(selected['url'], None)
        
        # Stream the actual .m3u8 playlist or segments
        # Fetch the playlist/segment
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
        
        if resp.status_code not in (200, 206):
            abort(502, f'HLS source returned {resp.status_code}')
        
        # For playlist files (.m3u8), rewrite URLs to proxy through our server
        content_type = resp.headers.get('Content-Type', 'application/vnd.apple.mpegurl')
        
        if 'mpegurl' in content_type or url.endswith('.m3u8'):
            # Parse and rewrite playlist
            playlist_content = resp.text
            
            # Rewrite relative URLs to absolute, proxied URLs
            lines = playlist_content.split('\n')
            rewritten = []
            
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    # This is a URI line
                    full_url = urljoin(url, line)
                    # Proxy through our /stream endpoint
                    proxied_url = f"/stream?url={requests.utils.quote(full_url, safe='')}"
                    rewritten.append(proxied_url)
                else:
                    rewritten.append(line)
            
            playlist_content = '\n'.join(rewritten)
            
            return Response(
                playlist_content,
                status=200,
                headers={
                    'Content-Type': content_type,
                    'Cache-Control': 'no-cache',
                }
            )
        else:
            # Binary segment file (.ts, .m4s, etc.)
            response_headers = {
                'Content-Type': content_type,
                'Cache-Control': 'max-age=31536000',
            }
            
            if 'Content-Length' in resp.headers:
                response_headers['Content-Length'] = resp.headers['Content-Length']
            
            def generate_hls_chunk():
                try:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            yield chunk
                except Exception as e:
                    logger.error(f"Error streaming HLS segment: {e}")
                finally:
                    resp.close()
            
            return Response(generate_hls_chunk(), status=200, headers=response_headers)
    
    except requests.RequestException as e:
        logger.error(f"HLS streaming error for {url}: {e}")
        abort(502, 'Cannot reach HLS source')


@app.route('/api/recent')
def get_recent():
    """Get recently streamed links from localStorage (client-side managed)."""
    return jsonify({'message': 'Recent links are stored in browser localStorage'})


@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': str(e.description)}), 400


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/get-audio-variant')
def get_audio_variant():
    """Get HLS variant playlist with specific audio track selected."""
    url = request.args.get('url', '').strip()
    audio_lang = request.args.get('audio', '').strip()
    
    if not url or not audio_lang:
        abort(400, 'Missing url or audio parameter')
    
    try:
        # Parse the master playlist
        hls_info = parse_hls_playlist(url)
        if not hls_info:
            abort(400, 'Failed to parse HLS playlist')
        
        # Find the variant with requested audio
        matching_variant = None
        for variant in hls_info['variants']:
            # Check if this variant has the requested audio group
            if variant.get('audio') == audio_lang:
                matching_variant = variant
                break
        
        if matching_variant:
            return jsonify({
                'url': matching_variant['url'],
                'bandwidth': matching_variant['bandwidth'],
                'resolution': matching_variant['resolution'],
            })
        else:
            # Fallback to first variant if exact match not found
            if hls_info['variants']:
                return jsonify({
                    'url': hls_info['variants'][0]['url'],
                    'bandwidth': hls_info['variants'][0]['bandwidth'],
                    'resolution': hls_info['variants'][0]['resolution'],
                })
            else:
                abort(400, 'No variants found')
    
    except Exception as e:
        logger.error(f"Error getting audio variant: {e}")
        abort(502, 'Error processing audio variant request')

@app.errorhandler(502)
def bad_gateway(e):
    return jsonify({'error': 'Cannot reach video source'}), 502


@app.errorhandler(504)
def timeout_error(e):
    return jsonify({'error': 'Video source timeout'}), 504


if __name__ == '__main__':
    logger.info("Starting Video Streaming Server")
    app.run(debug=True, host='0.0.0.0', port=5000)
