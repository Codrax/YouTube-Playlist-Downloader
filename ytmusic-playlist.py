#!/bin/python
import argparse
import sys
import os
import shutil
import json
import subprocess
import re

video_playback_gateway = "https://www.youtube.com/watch"

# ANSI Terminal Coloring Config
CLR_RESET = "\033[0m"
CLR_HEADER = "\033[1;36m"   # Cyan bold
CLR_SUCCESS = "\033[1;32m"  # Green bold
CLR_WARN = "\033[1;33m"     # Yellow bold
CLR_ERROR = "\033[1;31m"    # Red bold
CLR_INFO = "\033[0;34m"     # Blue regular
CLR_TEXT = "\033[0;35m"     # Magenta regular

class DataPipeline:
    def __init__(self):
        # Paths relative to the script execution directory
        self.output_dir = "./output"
        self.process_dir = "./process"
        self.cache_dir = "./cache/thumbnails"
        self.backup_dir = "./backup"

        # Binary overrides to use local files from your folder
        self.ytdlp_bin = "./yt-dlp"
        self.ffmpeg_bin = "./ffmpeg"

        # Ensure directories exist
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.process_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

    def _extract_playlist_id(self, url):
        """Helper to extract playlist ID or fall back to video ID / default name"""
        playlist_match = re.search(r'list=([^&]+)', url)
        if playlist_match:
            return playlist_match.group(1)

        video_match = re.search(r'(?:v=|\/v\/|youtu\.be\/)([^?&]+)', url)
        if video_match:
            return video_match.group(1)

        return "default_archive"

    def _get_already_downloaded_ids(self, archive_file):
        """Parse playlist.txt to find already completed video IDs"""
        downloaded_ids = set()
        if os.path.exists(archive_file):
            with open(archive_file, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[0] == "youtube":
                        downloaded_ids.add(parts[1])
        return downloaded_ids

    def download(self, url, cookies=None, quality="256k"):
        """DOWNLOAD"""
        playlist_id = self._extract_playlist_id(url)
        target_process_dir = os.path.join(self.process_dir, playlist_id)
        os.makedirs(target_process_dir, exist_ok=True)

        archive_file = os.path.join(target_process_dir, "playlist.txt")

        cookies_args = []
        if cookies:
            cookies_args = ["--cookies-from-browser", cookies]

        # Config initialization receipt panel display
        print(f"{CLR_TEXT}----------------------------------------{CLR_RESET}")
        print(f"{CLR_HEADER}       INITIALIZING PIPELINE RUN        {CLR_RESET}")
        print(f"{CLR_TEXT}----------------------------------------{CLR_RESET}")
        print(f"{CLR_INFO}Selected cookies from: {CLR_RESET}{cookies if cookies else 'None'}")
        print(f"{CLR_INFO}Quality setting:       {CLR_RESET}{quality}")
        print(f"{CLR_TEXT}----------------------------------------{CLR_RESET}\n")

        print(f"Starting fast index scan for: {url}...")

        flat_cmd = [
            self.ytdlp_bin,
            *cookies_args,
            "--flat-playlist",
            "--dump-json",
            url
        ]

        try:
            result = subprocess.run(flat_cmd, capture_output=True, text=True, check=True)
            all_entries = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        all_entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            downloaded_ids = self._get_already_downloaded_ids(archive_file)
            pending_entries = [e for e in all_entries if e.get('id') and e.get('id') not in downloaded_ids]

            total_pending = len(pending_entries)
            print(f"Playlist total: {len(all_entries)} | Already downloaded: {len(downloaded_ids)} | Missing/New: {total_pending}")

            if total_pending == 0:
                print("Success: All items up to date.")
                return

            for idx, entry in enumerate(pending_entries, start=1):
                video_id = entry['id']
                video_title = entry.get('title', video_id)
                if video_title in ["[Deleted video]", "[Private video]"]:
                    continue

                display_title = video_title[:35] + '...' if len(video_title) > 35 else video_title

                percent = int((idx / total_pending) * 100)
                bar_length = 20
                filled_length = int(bar_length * idx // total_pending)
                bar = '█' * filled_length + '-' * (bar_length - filled_length)

                sys.stdout.write(f"\r[{bar}] {percent}% | Processing item {idx}/{total_pending}: {display_title}")
                sys.stdout.flush()

                json_path = os.path.join(target_process_dir, f"{video_id}.json")
                video_url = f"{video_playback_gateway}?v={video_id}"

                info_cmd = [
                    self.ytdlp_bin,
                    *cookies_args,
                    "--dump-json",
                    video_url
                ]
                info_result = subprocess.run(info_cmd, capture_output=True, text=True)

                if info_result.returncode == 0:
                    video_data = json.loads(info_result.stdout.strip())

                    extracted_year = video_data.get("release_year")
                    if not extracted_year:
                        upload_date = video_data.get("upload_date", "")
                        if len(upload_date) >= 4:
                            extracted_year = int(upload_date[:4])

                    custom_metadata = {
                        "title": video_data.get("title", ""),
                        "artist": video_data.get("artist") or video_data.get("uploader", ""),
                        "description": video_data.get("description", ""),
                        "url": video_url,
                        "year": extracted_year,
                        "album": video_data.get("album", ""),
                        "album-artist": video_data.get("album_artist", ""),
                        "genre": video_data.get("genre", ""),
                        "track-number": video_data.get("track_number"),
                        "track-count": video_data.get("track_count"),
                        "image": {
                            "720": f"https://i.ytimg.com/vi/{video_id}/hq720.jpg",
                            "max": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                            "hq": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                            "mq": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
                        }
                    }

                    with open(json_path, 'w', encoding='utf-8') as jf:
                        json.dump(custom_metadata, jf, indent=4)

                dl_cmd = [
                    self.ytdlp_bin,
                    *cookies_args,
                    "--ffmpeg-location", self.ffmpeg_bin,
                    "-x",
                    "--audio-format", "mp3",
                    "--audio-quality", quality,
                    "--download-archive", archive_file,
                    "--output", os.path.join(target_process_dir, "%(id)s.%(ext)s"),
                    video_url
                ]
                subprocess.run(dl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

            print("\nSuccess: Download phase completed.")

        except subprocess.CalledProcessError as e:
            cmd_string = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in e.cmd)

            print(f"\n{CLR_ERROR}[Pipeline Error] Command failed with exit code {e.returncode}{CLR_RESET}", file=sys.stderr)
            print(f"{CLR_INFO}Failed Command:{CLR_RESET} {cmd_string}\n", file=sys.stderr)

            if e.stdout: print(e.stdout, file=sys.stderr, end='')
            if e.stderr: print(e.stderr, file=sys.stderr, end='')
            sys.exit(1)

    def _clean_title(self, title):
        """Cleans up YouTube junk words, bracket styles, and removes all emojis"""
        title = re.sub(r'[「」♡]', '', title)
        clutter_patterns = [
            r'\(Lyrics\)', r'\[Official Lyric Video\]', r'\(Official Video\)',
            r'\(Official Audio\)', r'\(Video\)', r'\[Official Video\]',
            r'\(Lyric Video\)', r'\[Lyric Video\]'
        ]
        for pattern in clutter_patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE)

        title = title.encode('ascii', 'ignore').decode('ascii')
        title = re.sub(r'\s+', ' ', title)
        return title.strip()

    def _display_terminal_thumbnail(self, image_path):
        """Attempts to display the cover art inside the active terminal emulator"""
        print(f"{CLR_INFO}--- Artwork Canvas Display ---{CLR_RESET}")
        try:
            if shutil.which("chafa"):
                subprocess.run(["chafa", "--size=30x15", image_path])
            elif shutil.which("wezterm"):
                subprocess.run(["wezterm", "imgcat", "--height=15", image_path])
            elif shutil.which("tiv"):
                subprocess.run(["tiv", "-h", "15", image_path])
            else:
                print(f"{CLR_WARN}[System Note] Install 'chafa' or use WezTerm to see visual terminal image rendering.{CLR_RESET}")
        except Exception as e:
            print(f"Failed drawing thumbnail preview: {e}")

    def _process_image_cropping(self, local_img_path):
        """Checks aspect ratios and provides 1:1 image box cropping transformations with recursive confirmation"""
        from PIL import Image as PILImage
        while True:
            try:
                with PILImage.open(local_img_path) as img:
                    w, h = img.size
                    if w == h:
                        return local_img_path

                    print(f"{CLR_WARN}The image aspect ratio is asymmetric ({w}x{h}).{CLR_RESET}")
                    print(f"Crop selection options: [none/n/start/s/center/c/end/e] (Default=Center):")
                    crop_mode = input(">> ").strip().lower()
                    if crop_mode == '':
                        crop_mode = 'c'

                    if crop_mode in ['none', 'n']:
                        return local_img_path

                    min_edge = min(w, h)
                    if w > h:
                        if crop_mode in ['start', 's']:
                            box = (0, 0, min_edge, min_edge)
                        elif crop_mode in ['end', 'e']:
                            box = (w - min_edge, 0, w, min_edge)
                        else:
                            offset = (w - min_edge) // 2
                            box = (offset, 0, offset + min_edge, min_edge)
                    else:
                        if crop_mode in ['start', 's']:
                            box = (0, 0, min_edge, min_edge)
                        elif crop_mode in ['end', 'e']:
                            box = (0, h - min_edge, min_edge, h)
                        else:
                            offset = (h - min_edge) // 2
                            box = (0, offset, min_edge, offset + min_edge)

                    cropped_img = img.crop(box)
                    cropped_path = os.path.splitext(local_img_path)[0] + "_cropped.jpg"
                    cropped_img.save(cropped_path, "JPEG")

                    print(f"\n{CLR_INFO}Displaying cropped layout validation preview...{CLR_RESET}")
                    self._display_terminal_thumbnail(cropped_path)

                    sat_choice = input("Are you satisfied with the crop? [Y/n]: ").strip().lower()
                    if sat_choice != 'n':
                        return cropped_path
                    else:
                        print(f"{CLR_WARN}Re-trying image boundary slicing choice...{CLR_RESET}")
            except Exception as e:
                print(f"{CLR_ERROR}Failed processing image boundaries: {e}{CLR_RESET}")
                return local_img_path

    def _fetch_itunes_meta(self, term):
        """Queries the iTunes API with proper URL encoding configuration"""
        import requests
        from urllib.parse import quote
        encoded_term = quote(term)
        url = f"https://itunes.apple.com/search/?media=music&limit=10&term={encoded_term}"
        try:
            headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("resultCount", 0) == 0: return []
                return data.get("results", [])
        except Exception as e:
            print(f"\n{CLR_WARN}[Warning] Network request or parsing failed: {e}{CLR_RESET}")
        return []

    def _write_mp3_tags(self, mp3_path, meta, local_cover_path=None):
        """Embeds ID3 tags and local artwork image data securely inside container"""
        from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, TDRC, TCON, TRCK, APIC
        try:
            tags = ID3(mp3_path)
        except Exception:
            tags = ID3()

        if meta.get("title"): tags.add(TIT2(encoding=3, text=meta["title"]))
        if meta.get("artist"): tags.add(TPE1(encoding=3, text=meta["artist"]))

        alb_art = meta.get("album_artist") if meta.get("album_artist") else meta.get("artist")
        if alb_art: tags.add(TPE2(encoding=3, text=alb_art))

        if meta.get("album"): tags.add(TALB(encoding=3, text=meta["album"]))
        if meta.get("year"): tags.add(TDRC(encoding=3, text=str(meta["year"])))
        if meta.get("genre"): tags.add(TCON(encoding=3, text=meta["genre"]))

        if meta.get("track_number"):
            tags.add(TRCK(encoding=3, text=str(meta["track_number"])))

        if local_cover_path and os.path.exists(local_cover_path):
            try:
                with open(local_cover_path, 'rb') as img_file:
                    img_data = img_file.read()
                tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data))
            except Exception as e:
                print(f"\n{CLR_ERROR}[Error] Failed embedding local cover layer: {e}{CLR_RESET}")

        tags.save(mp3_path)

    def _handle_pipeline_cleanup(self, playlist_path, video_id, json_path, mp3_path, preserve, backup_active):
        """Internal worker logic managing post-processing cleanup allocations"""
        if backup_active:
            target_backup_dir = os.path.join(self.backup_dir, os.path.basename(playlist_path))
            os.makedirs(target_backup_dir, exist_ok=True)

            if os.path.exists(mp3_path):
                shutil.move(mp3_path, os.path.join(target_backup_dir, f"{video_id}.mp3"))
            if os.path.exists(json_path):
                shutil.move(json_path, os.path.join(target_backup_dir, f"{video_id}.json"))
            print(f"{CLR_INFO}Cache resources safely archived into backup directory folder.{CLR_RESET}")
        elif not preserve:
            if os.path.exists(json_path): os.remove(json_path)
            if os.path.exists(mp3_path): os.remove(mp3_path)

    def process(self, preserve=False, backup_active=False):
        """PROCESS DOWNLOADED WITH INTEGRATED ARTIFACT HOOKS AND PIPELINE WRAPPERS"""
        from prompt_toolkit import prompt
        import requests

        print(f"{CLR_HEADER}Starting processing phase...{CLR_RESET}\n")

        if not os.path.exists(self.process_dir):
            print("Nothing to process.")
            return

        try:
            for playlist_id in os.listdir(self.process_dir):
                playlist_path = os.path.join(self.process_dir, playlist_id)
                if not os.path.isdir(playlist_path): continue

                print(f"{CLR_TEXT}========================================{CLR_RESET}")
                print(f"{CLR_HEADER}Processing Playlist ID: {playlist_id}{CLR_RESET}")
                print(f"{CLR_TEXT}========================================{CLR_RESET}")

                # Collect and sort local files to maintain a consistent linear index layout
                json_files = sorted([f for f in os.listdir(playlist_path) if f.endswith(".json")])

                file_idx = 0
                while file_idx < len(json_files):
                    file_name = json_files[file_idx]
                    video_id = file_name[:-5]
                    json_path = os.path.join(playlist_path, file_name)
                    mp3_path = os.path.join(playlist_path, f"{video_id}.mp3")

                    if not os.path.exists(mp3_path):
                        file_idx += 1
                        continue

                    with open(json_path, 'r', encoding='utf-8') as jf:
                        yt_meta = json.load(jf)

                    # --- EXPLICIT SEPARATED CACHE TARGETS DEFINITION ---
                    yt_art_cache = os.path.join(self.cache_dir, f"yt_{video_id}_raw.jpg")
                    itunes_art_cache = os.path.join(self.cache_dir, f"itunes_{video_id}_raw.jpg")
                    final_art_cache = os.path.join(self.cache_dir, f"final_{video_id}_square.jpg")

                    img_opts = yt_meta.get("image", {})
                    fallback_art = img_opts.get("max") or img_opts.get("720") or img_opts.get("hq") or ""

                    if fallback_art and not os.path.exists(yt_art_cache):
                        try:
                            img_data = requests.get(fallback_art, timeout=5).content
                            with open(yt_art_cache, 'wb') as f:
                                f.write(img_data)
                        except Exception:
                            pass

                    # --- INITIAL VIDEO INFO PANEL DISPLAY WITH THUMBNAIL ---
                    print(f"\n{CLR_TEXT}----------------------------------------{CLR_RESET}")
                    print(f"{CLR_HEADER}        TARGET SOURCE VIDEO INFO         {CLR_RESET}")
                    print(f"{CLR_TEXT}----------------------------------------{CLR_RESET}")
                    print(f"{CLR_INFO}Video ID: {CLR_RESET}{video_id}")
                    print(f"{CLR_INFO}URL:      {CLR_RESET}{yt_meta.get('url', f'{video_playback_gateway}?v={video_id}')}")
                    print(f"{CLR_INFO}Title:    {CLR_RESET}{yt_meta.get('title', 'Unknown')}")
                    print(f"{CLR_INFO}Artist:   {CLR_RESET}{yt_meta.get('artist', 'Unknown')}")
                    print(f"{CLR_INFO}Year:     {CLR_RESET}{yt_meta.get('year', 'Unknown')}")
                    print(f"{CLR_TEXT}----------------------------------------{CLR_RESET}")
                    if os.path.exists(yt_art_cache):
                        self._display_terminal_thumbnail(yt_art_cache)

                    # Refactored entry prompt to accommodate backward 'b' navigation mappings
                    process_choice = input("\nEdit file? [Y/n/b] (b = Go back to previous file): ").strip().lower()

                    if process_choice == 'b':
                        if file_idx > 0:
                            print(f"{CLR_WARN}Looping backward to previous track file context frame...{CLR_RESET}")
                            file_idx -= 1
                        else:
                            print(f"{CLR_ERROR}Already at the very first file in the directory line container.{CLR_RESET}")
                        continue
                    elif process_choice == 'n':
                        print(f"{CLR_WARN}Skipping loop allocation window context block.{CLR_RESET}")
                        file_idx += 1
                        continue

                    base_title = self._clean_title(yt_meta.get("title", ""))
                    base_artist = yt_meta.get("artist", "").strip()
                    base_artist = base_artist.encode('ascii', 'ignore').decode('ascii')

                    suggested_search = base_title
                    if base_artist and base_artist not in base_title:
                        suggested_search = f"{base_artist} - {base_title}"

                    processed_flag = False
                    skip_to_next_file = False

                    while True:
                        print(f"\nEdit search query (ENTER to confirm query):")
                        search_query = prompt(">> ", default=suggested_search).strip()

                        if not search_query:
                            print(f"{CLR_WARN}Skipping track entry due to empty search instruction.{CLR_RESET}")
                            break

                        retry_search = False
                        while True:
                            print(f"{CLR_INFO}Searching iTunes API for: '{search_query}'...{CLR_RESET}")
                            results = self._fetch_itunes_meta(search_query)

                            selected_meta = None
                            skip_itunes = False

                            if results:
                                print(f"\nFound {len(results)} matches:")
                                for idx, item in enumerate(results, start=1):
                                    track_title = item.get('trackName', 'Invalid name')
                                    artist_name = item.get('artistName', 'Unknown')
                                    album_name = item.get('collectionName', 'Unknown')
                                    release_year = item.get('releaseDate', '')[:4] or '0'
                                    print(f"  [{idx}] {artist_name} - {track_title} | Album: {album_name} ({release_year})")

                                first_item_art = results[0].get("artworkUrl100", "").replace("100x100", "600x600")
                                itunes_preview_cache = os.path.join(self.cache_dir, f"itunes_{video_id}_temp.jpg")
                                if first_item_art:
                                    try:
                                        ti_data = requests.get(first_item_art, timeout=5).content
                                        with open(itunes_preview_cache, 'wb') as f:
                                            f.write(ti_data)
                                        print(f"\n{CLR_INFO}[iTunes Top Hit Artwork Preview]{CLR_RESET}")
                                        self._display_terminal_thumbnail(itunes_preview_cache)
                                    except Exception:
                                        pass

                                action = input(f"\nUse result? [Y/n/r/index] (ENTER=1st, r=retry text prompt, n=skip iTunes): ").strip()

                                if os.path.exists(itunes_preview_cache): os.remove(itunes_preview_cache)

                                if action.lower() == 'n':
                                    skip_itunes = True
                                elif action.lower() == 'r':
                                    suggested_search = search_query
                                    retry_search = True
                                    break
                                elif action.isdigit():
                                    idx_choice = int(action) - 1
                                    if 0 <= idx_choice < len(results):
                                        selected_meta = results[idx_choice]
                                        chosen_art = selected_meta.get("artworkUrl100", "").replace("100x100", "600x600")
                                        if chosen_art:
                                            try:
                                                img_data = requests.get(chosen_art, timeout=5).content
                                                with open(itunes_art_cache, 'wb') as f: f.write(img_data)
                                            except Exception: pass
                                    else:
                                        print(f"{CLR_ERROR}Invalid selection index. Defaulting to skip.{CLR_RESET}")
                                        skip_itunes = True
                                else:
                                    selected_meta = results[0]
                                    if first_item_art:
                                        try:
                                            img_data = requests.get(first_item_art, timeout=5).content
                                            with open(itunes_art_cache, 'wb') as f: f.write(img_data)
                                        except Exception: pass

                                # --- SHOW CHOSEN ITUNES TEXT INFO + ARTWORK PREVIEW ---
                                if selected_meta and not skip_itunes:
                                    print(f"\n{CLR_TEXT}----------------------------------------{CLR_RESET}")
                                    print(f"{CLR_HEADER}       SELECTED ITUNES METADATA         {CLR_RESET}")
                                    print(f"{CLR_TEXT}----------------------------------------{CLR_RESET}")
                                    print(f"{CLR_INFO}Title:  {CLR_RESET}{selected_meta.get('trackName', 'Unknown')}")
                                    print(f"{CLR_INFO}Artist: {CLR_RESET}{selected_meta.get('artistName', 'Unknown')}")
                                    print(f"{CLR_INFO}Album:  {CLR_RESET}{selected_meta.get('collectionName', 'Unknown')}")
                                    print(f"{CLR_INFO}Year:   {CLR_RESET}{selected_meta.get('releaseDate', '')[:4]}")
                                    print(f"{CLR_INFO}Genre:  {CLR_RESET}{selected_meta.get('primaryGenreName', 'Unknown')}")
                                    print(f"{CLR_TEXT}----------------------------------------{CLR_RESET}")

                                    if os.path.exists(itunes_art_cache):
                                        self._display_terminal_thumbnail(itunes_art_cache)
                                        # iTunes results are square already, copy over to final target cache path directly
                                        shutil.copy2(itunes_art_cache, final_art_cache)

                            else:
                                print(f"{CLR_ERROR}No results were found on iTunes.{CLR_RESET}")
                                action = input("Retry search text or skip to YouTube info? [r=retry text prompt, n=skip iTunes]: ").strip()
                                if action.lower() == 'r':
                                    suggested_search = search_query
                                    retry_search = True
                                    break
                                else:
                                    skip_itunes = True

                            final_tags = {}

                            if selected_meta and not skip_itunes:
                                final_tags = {
                                    "title": selected_meta.get("trackName"),
                                    "artist": selected_meta.get("artistName"),
                                    "album_artist": selected_meta.get("artistName"),
                                    "album": selected_meta.get("collectionName"),
                                    "year": selected_meta.get("releaseDate", "")[:4],
                                    "genre": selected_meta.get("primaryGenreName"),
                                    "track_number": selected_meta.get("trackNumber")
                                }
                                processed_flag = True
                            else:
                                while True:
                                    use_yt = input("Would you like to use the YouTube video information? [Y/n]: ").strip()
                                    if use_yt.lower() != 'n':
                                        print("\n--- Review metadata details (Edit inline) ---")

                                        final_tags["title"] = prompt("Title >> ", default=str(base_title)).strip()
                                        final_tags["artist"] = prompt("Artist >> ", default=str(base_artist)).strip()

                                        default_alb_art = yt_meta.get("album-artist", "") if yt_meta.get("album-artist") else final_tags["artist"]
                                        final_tags["album_artist"] = prompt("Album Artist >> ", default=str(default_alb_art)).strip()
                                        final_tags["album"] = prompt("Album >> ", default=str(yt_meta.get("album", ""))).strip()
                                        final_tags["year"] = prompt("Year >> ", default=str(yt_meta.get("year" or ""))).strip()
                                        final_tags["genre"] = prompt("Genre >> ", default=str(yt_meta.get("genre", ""))).strip()

                                        raw_trck = str(yt_meta.get("track-number") or "")
                                        user_trck = prompt("Track Number >> ", default=raw_trck).strip()
                                        if user_trck == "":
                                            final_tags["track_number"] = "1"
                                        elif user_trck.lower() == "none":
                                            final_tags["track_number"] = ""
                                        else:
                                            final_tags["track_number"] = user_trck

                                        print(f"\n{CLR_INFO}[Pre-Crop Visual Canvas]{CLR_RESET}")
                                        if os.path.exists(yt_art_cache):
                                            self._display_terminal_thumbnail(yt_art_cache)

                                        final_artwork_url = prompt("Thumbnail URL >> ", default=str(fallback_art)).strip()

                                        if final_artwork_url:
                                            try:
                                                # Temporarily save customized inputs out of standard namespace blocks
                                                custom_temp_path = os.path.join(self.cache_dir, f"custom_raw_{video_id}.jpg")
                                                img_data = requests.get(final_artwork_url, timeout=5).content
                                                with open(custom_temp_path, 'wb') as f:
                                                    f.write(img_data)

                                                cropped_output = self._process_image_cropping(custom_temp_path)
                                                if os.path.exists(cropped_output):
                                                    shutil.copy2(cropped_output, final_art_cache)
                                                    if cropped_output.endswith("_cropped.jpg"):
                                                        os.remove(cropped_output)
                                                if os.path.exists(custom_temp_path):
                                                    os.remove(custom_temp_path)
                                            except Exception as e:
                                                print(f"Failed handling image URL link: {e}")
                                        else:
                                            # If using wide youtube default fallback artwork directly
                                            if os.path.exists(yt_art_cache):
                                                cropped_output = self._process_image_cropping(yt_art_cache)
                                                if os.path.exists(cropped_output):
                                                    shutil.copy2(cropped_output, final_art_cache)
                                                    if cropped_output.endswith("_cropped.jpg"):
                                                        os.remove(cropped_output)

                                        print("\n--- Field summary complete ---")
                                        fix_choice = input("Are these fields correct? [Y/r/n] (ENTER=yes, r=re-edit details, n=cancel tags): ").strip()
                                        if fix_choice.lower() == 'r':
                                            base_title = final_tags["title"]
                                            base_artist = final_tags["artist"]
                                            yt_meta["album-artist"] = final_tags["album_artist"]
                                            yt_meta["album"] = final_tags["album"]
                                            yt_meta["year"] = final_tags["year"]
                                            yt_meta["genre"] = final_tags["genre"]
                                            yt_meta["track-number"] = final_tags["track_number"]
                                            fallback_art = final_artwork_url
                                            continue
                                        elif fix_choice.lower() == 'n':
                                            final_tags = {}
                                            break
                                        else:
                                            processed_flag = True
                                            break
                                    else:
                                        break

                            if final_tags and processed_flag:
                                if not final_tags.get("album") or str(final_tags["album"]).strip() == "":
                                    album_title_base = final_tags.get("title") if final_tags.get("title") else base_title
                                    final_tags["album"] = f"{album_title_base} - Single"

                                save_confirm = input("Do you want to save the information to the MP3 file? [Y/n]: ").strip()
                                if save_confirm.lower() != 'n':
                                    active_cover_embed = final_art_cache if os.path.exists(final_art_cache) else (yt_art_cache if os.path.exists(yt_art_cache) else None)
                                    self._write_mp3_tags(mp3_path, final_tags, active_cover_embed)

                                    safe_artist = re.sub(r'[\\/*?:"<>|]', "", final_tags["artist"] or "Unknown Artist")
                                    safe_title = re.sub(r'[\\/*?:"<>|]', "", final_tags["title"] or "Unknown Title")

                                    dest_artist_dir = os.path.join(self.output_dir, safe_artist)
                                    os.makedirs(dest_artist_dir, exist_ok=True)
                                    dest_mp3_path = os.path.join(dest_artist_dir, f"{safe_title}.mp3")

                                    shutil.copy2(mp3_path, dest_mp3_path)
                                    print(f"{CLR_SUCCESS}Successfully deployed file format: {dest_mp3_path}{CLR_RESET}")

                                    # Clean current tracking run cache elements safely
                                    for cache_f in [yt_art_cache, itunes_art_cache, final_art_cache]:
                                        if os.path.exists(cache_f):
                                            os.remove(cache_f)

                                    self._handle_pipeline_cleanup(playlist_path, video_id, json_path, mp3_path, preserve, backup_active)

                                    json_files.pop(file_idx)
                                    skip_to_next_file = True
                                else:
                                    processed_flag = False
                            break # Breaks the inner iTunes search loop
                        if not retry_search: break

                    if skip_to_next_file:
                        continue # Go to the next file in the list, don't break the whole loop!

                    if not processed_flag:
                        print(f"\n{CLR_WARN}No processing made for this track.{CLR_RESET}")
                        del_choice = input("Delete this file from incoming process directory? [y/N]: ").strip().lower()
                        if del_choice == 'y':
                            if os.path.exists(json_path): os.remove(json_path)
                            if os.path.exists(mp3_path): os.remove(mp3_path)
                            print(f"{CLR_SUCCESS}Discarded un-tagged track metadata files cleanly.{CLR_RESET}")
                            json_files.pop(file_idx)
                        else:
                            if backup_active:
                                self._handle_pipeline_cleanup(playlist_path, video_id, json_path, mp3_path, preserve, backup_active)
                                json_files.pop(file_idx)
                            else:
                                # Progress safely forward to next candidate loop index reference
                                file_idx += 1
                        break

        except KeyboardInterrupt:
            print(f"\n\n{CLR_ERROR}Detected Ctrl+C. Exiting...{CLR_RESET}")
            sys.exit(0)

        print(f"\n{CLR_SUCCESS}Success: Process operations completed.{CLR_RESET}")

    def edit(self):
        """EDIT OPERATION MODE: Scans output/ folder to interactively rewrite metadata fields inside existing MP3 files"""
        from prompt_toolkit import prompt
        from mutagen.id3 import ID3
        import requests
        import hashlib

        print(f"{CLR_HEADER}Starting output deployment inline modification phase...{CLR_RESET}\n")

        if not os.path.exists(self.output_dir):
            print("No output targets deployment folder infrastructure found.")
            return

        mp3_targets = []
        for root, _, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith(".mp3"):
                    mp3_targets.append(os.path.join(root, f))

        if not mp3_targets:
            print("No complete deployable target .mp3 items found inside output folder.")
            return

        # Maintain sorted output files for a predictable line container index mapping layout
        mp3_targets = sorted(mp3_targets)

        try:
            mp3_idx = 0
            while mp3_idx < len(mp3_targets):
                mp3_path = mp3_targets[mp3_idx]
                print(f"\n{CLR_TEXT}========================================{CLR_RESET}")
                print(f"{CLR_INFO}File Location: {CLR_RESET}{mp3_path}")

                try:
                    tags = ID3(mp3_path)
                except Exception:
                    tags = {}

                current_title = str(tags.get("TIT2", "Unknown Title"))
                current_artist = str(tags.get("TPE1", "Unknown Artist"))
                current_album_artist = str(tags.get("TPE2", current_artist))
                current_album = str(tags.get("TALB", "Unknown Album"))
                current_year = str(tags.get("TDRC", ""))
                current_genre = str(tags.get("TCON", ""))
                current_track = str(tags.get("TRCK", ""))

                print(f"{CLR_INFO}Title:         {CLR_RESET}{current_title}")
                print(f"{CLR_INFO}Artist:        {CLR_RESET}{current_artist}")
                print(f"{CLR_INFO}Album:         {CLR_RESET}{current_album}")
                print(f"{CLR_INFO}Year:          {CLR_RESET}{current_year}")
                print(f"{CLR_INFO}Genre:         {CLR_RESET}{current_genre}")
                print(f"{CLR_INFO}Track:         {CLR_RESET}{current_track}")
                print(f"{CLR_TEXT}----------------------------------------{CLR_RESET}")

                file_hash = hashlib.md5(mp3_path.encode('utf-8')).hexdigest()[:10]
                local_active_art = os.path.join(self.cache_dir, f"edit_active_{file_hash}.jpg")

                # Extract existing art if it exists
                apic_frames = [key for key in tags.keys() if key.startswith("APIC")]
                if apic_frames:
                    try:
                        apic_data = tags[apic_frames[0]].data
                        with open(local_active_art, 'wb') as art_file:
                            art_file.write(apic_data)
                        self._display_terminal_thumbnail(local_active_art)
                    except Exception as e:
                        print(f"{CLR_WARN}[System Note] Could not parse embedded artwork frame: {e}{CLR_RESET}")

                # Added backward 'b' mapping choice into deployment framework loop blocks
                process_choice = input("\nEdit file? [y/N/b] (b = Go back to previous file): ").strip().lower()

                if process_choice == 'b':
                    if os.path.exists(local_active_art): os.remove(local_active_art)
                    if mp3_idx > 0:
                        print(f"{CLR_WARN}Looping backward to previous output file context frame...{CLR_RESET}")
                        mp3_idx -= 1
                    else:
                        print(f"{CLR_ERROR}Already at the very first output file in the container sequence.{CLR_RESET}")
                    continue
                elif process_choice != 'y':
                    if os.path.exists(local_active_art): os.remove(local_active_art)
                    mp3_idx += 1
                    continue

                while True:
                    print(f"\n{CLR_HEADER}--- Review/Modify Metadata Details ---{CLR_RESET}")
                    updated_meta = {
                        "title": prompt("Title >> ", default=current_title).strip(),
                        "artist": prompt("Artist >> ", default=current_artist).strip(),
                        "album_artist": prompt("Album Artist >> ", default=current_album_artist).strip(),
                        "album": prompt("Album >> ", default=current_album).strip(),
                        "year": prompt("Year >> ", default=current_year).strip(),
                        "genre": prompt("Genre >> ", default=current_genre).strip(),
                        "track_number": prompt("Track Number >> ", default=current_track).strip()
                    }

                    img_edit_choice = input("\nDo you want to load a new image URL? [y/N]: ").strip().lower()

                    if img_edit_choice == 'y':
                        img_url = prompt("New Image URL >> ").strip()
                        if img_url:
                            try:
                                print(f"{CLR_INFO}Fetching remote image layer...{CLR_RESET}")
                                img_data = requests.get(img_url, timeout=5).content
                                with open(local_active_art, 'wb') as f:
                                    f.write(img_data)
                            except Exception as e:
                                print(f"{CLR_ERROR}Failed to download or parse new image file: {e}{CLR_RESET}")

                    # --- FIXED: CROPPING ENGINE RUNS REGARDLESS OF THE SELECTION ---
                    if os.path.exists(local_active_art):
                        processed_crop = self._process_image_cropping(local_active_art)

                        # If a cropped variant was produced, overwrite local active cache cleanly
                        if processed_crop != local_active_art:
                            shutil.copy2(processed_crop, local_active_art)
                            if processed_crop.endswith("_cropped.jpg") and os.path.exists(processed_crop):
                                os.remove(processed_crop)

                        self._display_terminal_thumbnail(local_active_art)

                    print(f"\n--- Field modification complete ---")
                    save_choice = input("Do you want to save your changes? [Y/r/n] (r=re-edit details): ").strip().lower()

                    if save_choice == 'r':
                        current_title = updated_meta["title"]
                        current_artist = updated_meta["artist"]
                        current_album_artist = updated_meta["album_artist"]
                        current_album = updated_meta["album"]
                        current_year = updated_meta["year"]
                        current_genre = updated_meta["genre"]
                        current_track = updated_meta["track_number"]
                        continue
                    elif save_choice == 'n':
                        print(f"{CLR_WARN}Modifications cancelled for this file.{CLR_RESET}")
                        if os.path.exists(local_active_art): os.remove(local_active_art)
                        mp3_idx += 1
                        break
                    else:
                        active_embed = local_active_art if os.path.exists(local_active_art) else None
                        self._write_mp3_tags(mp3_path, updated_meta, active_embed)

                        if os.path.exists(local_active_art): os.remove(local_active_art)

                        safe_artist = re.sub(r'[\\/*?:"<>|]', "", updated_meta["artist"] or "Unknown Artist")
                        safe_title = re.sub(r'[\\/*?:"<>|]', "", updated_meta["title"] or "Unknown Title")

                        expected_dir = os.path.join(self.output_dir, safe_artist)
                        expected_path = os.path.join(expected_dir, f"{safe_title}.mp3")

                        if os.path.abspath(mp3_path) != os.path.abspath(expected_path):
                            os.makedirs(expected_dir, exist_ok=True)
                            shutil.move(mp3_path, expected_path)
                            print(f"{CLR_SUCCESS}Moved file structure tracking updates to: {expected_path}{CLR_RESET}")
                            mp3_targets[mp3_idx] = expected_path
                        else:
                            print(f"{CLR_SUCCESS}Successfully applied in-place ID3 metadata field updates!{CLR_RESET}")

                        mp3_idx += 1
                        break

        except KeyboardInterrupt:
            print(f"\n\n{CLR_ERROR}Detected Ctrl+C. Exiting edit sequence context...{CLR_RESET}")
            sys.exit(0)

        print(f"\n{CLR_SUCCESS}Success: Edit actions phase sequence completed.{CLR_RESET}")

    def purge(self):
        """PURGE METHOD"""
        print(f"Purging contents inside process directory: {self.process_dir}...")
        if os.path.exists(self.process_dir):
            for item in os.listdir(self.process_dir):
                item_path = os.path.join(self.process_dir, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                except Exception as e:
                    print(f"Failed to delete {item_path}: {e}", file=sys.stderr)
        print("Success: Process directory cleared.")

def main():
    pipeline = DataPipeline()
    parser = argparse.ArgumentParser(description="A CLI tool with download youtube music playlists.")
    subparsers = parser.add_subparsers(dest='action', required=True, help="Available methods")

    download_parser = subparsers.add_parser('download', help='Download data from a source')
    download_parser.add_argument('url', type=str, help='The target URL to download from')
    # Changes applied here: Generic cookies string selection and quality controls strings
    download_parser.add_argument('--cookies', type=str, help='Browser name to extract cookies from (e.g. firefox, chrome, brave)')
    download_parser.add_argument('--quality', type=str, choices=['128k', '256k', '320k'], default='256k', help='Audio quality bit rate option')

    process_parser = subparsers.add_parser('process', help='Process the downloaded data')
    process_parser.add_argument('--preserve', action='store_true', help='Keep intermediate source cache files')
    process_parser.add_argument('--backup', action='store_true', help='Move intermediate files to backup folder instead of deleting')

    subparsers.add_parser('edit', help='Modify and update ID3 metadata parameters inside output/ folder files interactively')

    subparsers.add_parser('purge', help='Clear the process directory contents')
    args = parser.parse_args()

    if args.action == 'download':
        pipeline.download(url=args.url, cookies=args.cookies, quality=args.quality)
    elif args.action == 'process':
        pipeline.process(preserve=args.preserve, backup_active=args.backup)
    elif args.action == 'edit':
        pipeline.edit()
    elif args.action == 'purge':
        pipeline.purge()

if __name__ == "__main__":
    main()
