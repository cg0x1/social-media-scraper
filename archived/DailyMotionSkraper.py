import yt_dlp
import json
from typing import Dict, Any
import requests

class Skraper:

    def call_api(self, video_id: str, proxy: str):
        
        metadata_url = f"https://www.dailymotion.com/player/metadata/video/{video_id}"
        
        detail_url = "https://api.dailymotion.com/video/{video_id}?fields=views_total,likes_total,comments_total,bookmarks_total,created_time,duration,title,owner.username,owner.screenname,owner.id"
        
        headers = {
            # Dailymotion is generally fine without a User-Agent,
            # but adding one avoids edge-case blocking
            "User-Agent": "Mozilla/5.0 (compatible; metadata-fetch/1.0)",
            "Accept": "application/json",
        }

        response = requests.get(url = metadata_url,
                                headers=headers,
                                timeout=30,
                                proxies={
                                    "http": proxy,
                                    "https": proxy
                                },
                                json=True)
        
        response.raise_for_status()

        data = response.json()

        print(json.dumps(data, indent=2, ensure_ascii=False))
        pass

    """
    Extracts video information from a Dailmotion.com video URL

    Args:
        video_url (str): The DAILYMOTION Today URL.

    Returns:
        dict: A dictionary containing the video information, or None if an error occurs.
    """
    def get_video_info(self, video_url, proxy_address):

        ydl_opts = {
            'quiet': True,  # Suppress console output
            'no_warnings': True,  # Suppress warnings
            'extract_flat': "in_playlist", #get info about the video only, not the playlist.
            'skip_download': True, #do not download the video.
            'writeinfojson': False, #do not create a json file.
            'writesubtitles' : True,
            'writeautomaticsubtitles' : True,
            'print_json': True,
            'proxy': proxy_address,
            'nocheckcertificate' : True
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                
                info_json = ydl.extract_info(video_url, download=False)

                # extractor = yt_dlp.extractor.youtube.YoutubeIE(ydl)
                # extraction = extractor.extract_subtitles(video_url)
                # subtitles = extraction['subtitles']
                #return subtitles

                return info_json
                #return json.loads(json.dumps(info_json))
            #with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # try:
                #     info_dict = ydl.extract_info(video_url, download=False)
                #     if info_dict:
                #         return info_dict
                #     else:
                #         return None
                # except yt_dlp.utils.ExtractorError as e:
                #     print(f"Extractor error: {e}")
                #     return None
            #return None
        except yt_dlp.utils.DownloadError as e:
            print(f"Error: {e}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return None

    def summarize_info(info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Produce a small, readable summary from the full yt-dlp info dict.
        Handles single video or playlist-like responses.
        """
        def one(video: Dict[str, Any]) -> Dict[str, Any]:
            formats = video.get("formats") or []
            # Pick a few useful format fields
            top_formats = []
            for f in formats[:15]:  # don't spam
                top_formats.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "resolution": f.get("resolution") or f"{f.get('width')}x{f.get('height')}",
                    "fps": f.get("fps"),
                    "vcodec": f.get("vcodec"),
                    "acodec": f.get("acodec"),
                    "tbr": f.get("tbr"),
                    "url_present": bool(f.get("url")),
                })

            return {
                "id": video.get("id"),
                "title": video.get("title"),
                "uploader": video.get("uploader") or video.get("channel"),
                "uploader_id": video.get("uploader_id"),
                "timestamp": video.get("timestamp"),
                "duration": video.get("duration"),
                "view_count": video.get("view_count"),
                "like_count": video.get("like_count"),
                "comment_count": video.get("comment_count"),
                "tags": video.get("tags"),
                "thumbnails_count": len(video.get("thumbnails") or []),
                "subtitles_langs": sorted((video.get("subtitles") or {}).keys()),
                "automatic_captions_langs": sorted((video.get("automatic_captions") or {}).keys()),
                "webpage_url": video.get("webpage_url"),
                "extractor": video.get("extractor"),
                "formats_preview": top_formats,
            }

        # Playlist / multi-video case
        if "entries" in info and isinstance(info["entries"], list):
            entries = [e for e in info["entries"] if isinstance(e, dict)]
            return {
                "_type": info.get("_type"),
                "id": info.get("id"),
                "title": info.get("title"),
                "webpage_url": info.get("webpage_url"),
                "entries_count": len(entries),
                "entries": [one(v) for v in entries[:10]],  # preview first 10
            }

        # Single video case
        return one(info)

    def download_best_mp4(url: str, output_template: str = "%(title).200s [%(id)s].%(ext)s") -> None:
        """
        Optional: download media (best MP4 variant if available) and write a JSON info file.
        """
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": output_template,
            "writedescription": False,
            "writeinfojson": True,   # writes .info.json alongside the file
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "vtt/srt/best",
            "postprocessors": [
                {"key": "FFmpegMetadata"},  # embed metadata when possible (requires ffmpeg)
            ],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])