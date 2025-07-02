import os, json, boto3, uuid, subprocess, logging, traceback
from urllib.parse import urlparse, unquote

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def generate_silence(duration=0.7):
    """Create a silence MP3 file of given duration, return the file path."""
    silence_path = f"/tmp/silence_{uuid.uuid4()}.mp3"
    subprocess.run([
        "/usr/local/bin/ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
        "-q:a", "9",
        "-acodec", "libmp3lame",
        silence_path
    ], check=True)
    return silence_path


class AudioMixer:
    def __init__(self, output_bucket, music_bucket=None):
        self.s3 = boto3.client('s3')
        self.output_bucket = output_bucket
        self.music_bucket = music_bucket or output_bucket
        logger.info(f"[INIT] Output bucket: {output_bucket}, Music bucket: {self.music_bucket}")

    def parse_body(self, event):
        logger.info(f"[PARSE_BODY] Raw body: {event.get('body')}")
        body = event.get('body')
        while isinstance(body, str):
            try: body = json.loads(body)
            except Exception: break
        if not isinstance(body, dict): body = {}
        if 'body' in body and isinstance(body['body'], str):
            try:
                inner = json.loads(body['body'])
                if isinstance(inner, dict): body = inner
            except Exception: pass
        logger.info(f"[PARSE_BODY] Parsed body: {body}")
        return body

    def download_s3(self, bucket, key, local_path):
        logger.info(f"[S3_DOWNLOAD] Downloading s3://{bucket}/{key} to {local_path}")
        self.s3.download_file(bucket, key, local_path)
        logger.info(f"[S3_DOWNLOAD] Done downloading {key}")

    def concatenate_narration(self, bucket, chunk_keys):
        logger.info(f"[CONCATENATE] Downloading {len(chunk_keys)} narration chunks from bucket: {bucket}")
    
        logger.info(f"[DEBUG] chunk_keys ({len(chunk_keys)}): {chunk_keys}")
    
        local_paths = []
        for idx, key in enumerate(chunk_keys):
            local_path = f"/tmp/narr_{idx}_{uuid.uuid4()}.mp3"
            try:
                self.download_s3(bucket, key, local_path)
                logger.info(f"[DOWNLOAD] Chunk {idx}: key={key} -> {local_path}")
            except Exception as ex:
                logger.error(f"[DOWNLOAD_ERROR] Failed to fetch chunk {idx} ({key}): {ex}")
                continue
    
            exists = os.path.exists(local_path)
            size = os.path.getsize(local_path) if exists else -1
            dur = self.get_audio_duration(local_path) if exists else -1
            logger.info(f"[CHUNK {idx}] key: {key}, exists: {exists}, size: {size}, duration: {dur:.2f}s")
    
            if not exists:
                logger.error(f"[MISSING_CHUNK] File missing: {local_path} (key: {key})")
            elif size == 0:
                logger.error(f"[EMPTY_CHUNK] Zero-length file: {local_path} (key: {key})")
    
            local_paths.append(local_path)
    
            # --- Insert 1-second silence after every chunk except the last ---
            if idx < len(chunk_keys) - 1:
                silence_path = generate_silence(duration=1.0)
                local_paths.append(silence_path)
    
        if len(local_paths) == 1:
            logger.info("[CONCATENATE] Only one chunk, skipping concatenation.")
            return local_paths[0]
    
        concat_list = "/tmp/concat.txt"
        with open(concat_list, "w") as f:
            for p in local_paths:
                f.write(f"file '{p}'\n")
    
        with open(concat_list, "r") as f:
            logger.info(f"[CONCAT FILE] Contents:\n{f.read()}")
    
        concat_path = f"/tmp/narration_full_{uuid.uuid4()}.mp3"
        logger.info(f"[FFMPEG] Concatenating (re-encode) to {concat_path}")
    
        try:
            result = subprocess.run([
                "/usr/local/bin/ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c:a", "libmp3lame", "-ar", "44100", "-b:a", "328k", concat_path
            ], check=True, capture_output=True, text=True)
            logger.info(f"[FFMPEG] concat stdout: {result.stdout}")
            logger.info(f"[FFMPEG] concat stderr: {result.stderr}")
        except subprocess.CalledProcessError as e:
            logger.error(f"[FFMPEG_ERROR] {e.stderr}")
            raise
    
        if os.path.exists(concat_path):
            concat_dur = self.get_audio_duration(concat_path)
            concat_size = os.path.getsize(concat_path)
            logger.info(f"[CHECK] Concatenated narration duration: {concat_dur:.2f}s, size: {concat_size} bytes")
        else:
            logger.error("[ERROR] Concatenated file does not exist!")
    
        return concat_path


    def get_audio_duration(self, file_path):
        result = subprocess.run([
            "/usr/local/bin/ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ], capture_output=True, text=True)
        try:
            duration = float(result.stdout.strip())
        except Exception as e:
            logger.error(f"[DURATION_ERROR] {e} result: {result.stdout}")
            duration = 0
        logger.info(f"[DURATION] {file_path}: {duration} seconds")
        return duration

    def pad_narration(self, narration_path, pad_sec=0.15):
        silenced_path = f"/tmp/narr_sil_{uuid.uuid4()}.mp3"
        subprocess.run([
            "/usr/local/bin/ffmpeg", "-y",
            "-f", "lavfi", "-t", str(pad_sec), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-i", narration_path,
            "-filter_complex", "[0][1]concat=n=2:v=0:a=1[a]",
            "-map", "[a]", silenced_path
        ], check=True)
        logger.info(f"[PAD_NARRATION] Added {pad_sec}s silence: {silenced_path}")
        return silenced_path

    def adjust_music(self, music_path, narration_duration):
        music_duration = self.get_audio_duration(music_path)
        adjusted_path = f"/tmp/music_adj_{uuid.uuid4()}.mp3"
        if music_duration < narration_duration - 0.05:  # loop if too short
            logger.info("[ADJUST_MUSIC] Looping music to fit narration.")
            subprocess.run([
                "/usr/local/bin/ffmpeg", "-y", "-stream_loop", "-1",
                "-i", music_path, "-t", str(narration_duration), "-c", "copy", adjusted_path
            ], check=True)
        else:  # trim if too long or close enough
            logger.info("[ADJUST_MUSIC] Trimming music to fit narration.")
            subprocess.run([
                "/usr/local/bin/ffmpeg", "-y",
                "-i", music_path, "-t", str(narration_duration), "-c", "copy", adjusted_path
            ], check=True)
        return adjusted_path

    def process(self, event):
        logger.info(f"[PROCESS] Event received: {json.dumps(event)[:500]}")
        body = self.parse_body(event)
        chunk_keys = body.get('chunk_keys')
        narration_bucket = body.get('bucket')
        music_file = body.get('music', "")

        logger.info(f"[PROCESS] chunk_keys: {chunk_keys}, narration_bucket: {narration_bucket}, music_file: {music_file}")

        if not chunk_keys or not narration_bucket:
            logger.error(f"[ERROR] Missing 'chunk_keys' or 'bucket': {body}")
            return self.err(400, "Missing 'chunk_keys' or 'bucket'", got=body)

        try:
            narration_path = self.concatenate_narration(narration_bucket, chunk_keys)
        except Exception as e:
            logger.error(f"[CONCATENATE_ERROR] {e}")
            logger.error(traceback.format_exc())
            return self.err(500, f"Failed to concatenate narration: {e}", trace=traceback.format_exc())

        # Add 0.15s silence at the start (prevents cut-off)
        narration_path = self.pad_narration(narration_path, pad_sec=0.15)
        narration_duration = self.get_audio_duration(narration_path)

        output_path = f"/tmp/output_{uuid.uuid4()}.mp3"
        music_path = None

        if music_file:
            if music_file.startswith("http"):
                music_key = unquote(urlparse(music_file).path.lstrip("/"))
            else:
                music_key = unquote(music_file)
            music_path = f"/tmp/{os.path.basename(music_key)}"
            try:
                self.download_s3(self.music_bucket, music_key, music_path)
            except Exception as s3exc:
                logger.error(f"[S3_MUSIC_DOWNLOAD_ERROR] {s3exc}")
                logger.error(traceback.format_exc())
                return self.err(404, "Could not download music from S3",
                                bucket=self.music_bucket, key=music_key, trace=traceback.format_exc())

            # Adjust music duration to match narration duration (trim or loop)
            music_path = self.adjust_music(music_path, narration_duration)

            # Fade out music at end (last 2 seconds or 1/3 of audio, whichever is less)
            fade_len = min(5, int(narration_duration / 3))
            fade_len = max(fade_len, 0.8)  # At least 0.8 seconds fade

            filter_complex = (
                f"[0:a]volume=0.7,highpass=f=180,equalizer=f=100:t=q:w=2:g=-8[narr];"
                f"[1:a]afade=t=out:st={narration_duration-fade_len}:d={fade_len},volume=0.2[music];"
                f"[narr][music]amix=inputs=2:duration=first[aout]"
            )
            inputs = ["-i", narration_path, "-i", music_path]
            cmd = [
                "/usr/local/bin/ffmpeg", "-y", *inputs,
                "-filter_complex", filter_complex,
                "-map", "[aout]",
                "-c:a", "mp3", output_path
            ]
        else:
            filter_simple = "volume=0.7,highpass=f=120,equalizer=f=100:t=q:w=2:g=-8"
            inputs = ["-i", narration_path]
            cmd = [
                "/usr/local/bin/ffmpeg", "-y", *inputs,
                "-filter:a", filter_simple,
                "-c:a", "mp3", output_path
            ]

        logger.info(f"[FFMPEG] Running: {' '.join(str(c) for c in cmd)}")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"[FFMPEG_OUTPUT] {result.stdout}")
            logger.info(f"[FFMPEG_ERROR] {result.stderr}")
        except subprocess.CalledProcessError as e:
            logger.error(f"[FFMPEG_MIX_ERROR] {e.stderr}")
            logger.error(traceback.format_exc())
            return self.err(500, "Mixing failed", ffmpeg_error=e.stderr, trace=traceback.format_exc())

        logger.info(f"[FFMPEG] Audio processed, output: {output_path}")

        output_key = f"mixed/{uuid.uuid4()}.mp3"
        logger.info(f"[S3_UPLOAD] Uploading output to s3://{self.output_bucket}/{output_key}")
        try:
            self.s3.upload_file(output_path, self.output_bucket, output_key)
        except Exception as s3_exc:
            logger.error(f"[S3_UPLOAD_ERROR] {s3_exc}")
            logger.error(traceback.format_exc())
            return self.err(500, f"Failed to upload output: {s3_exc}", trace=traceback.format_exc())

        # Cleanup temp files
        try:
            os.remove(output_path)
            os.remove(narration_path)
            if music_path and os.path.exists(music_path):
                os.remove(music_path)
        except Exception as cleanup_exc:
            logger.warning(f"[CLEANUP_WARNING] {cleanup_exc}")

        url = self.s3.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': self.output_bucket, 'Key': output_key},
            ExpiresIn=3600
        )
        logger.info(f"[PRESIGNED_URL] Generated: {url}")

        return self.ok({
            "chunk_keys": chunk_keys,
            "bucket": narration_bucket,
            "download_url": url
        })

    def ok(self, body):
        logger.info(f"[RESPONSE 200] {body}")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(body)
        }

    def err(self, code, msg, **extra):
        logger.error(f"[RESPONSE {code}] {msg} {extra}")
        return {
            "statusCode": code,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": msg, **extra})
        }

def handler(event, context):
    try:
        mixer = AudioMixer(
            output_bucket=os.environ["OUTPUT_BUCKET"],
            music_bucket=os.environ.get("MUSIC_BUCKET")
        )
        return mixer.process(event)
    except Exception as e:
        logger.error("[UNHANDLED_EXCEPTION] %s", str(e))
        logger.error(traceback.format_exc())
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({
                "error": str(e),
                "trace": traceback.format_exc()
            })
        }
