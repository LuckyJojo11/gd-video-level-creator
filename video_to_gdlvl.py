#!/usr/bin/env python3
"""Turn a short video into a Vanilla Geometry Dash 2.209 video-screen level.

The program writes a Vanilla 2.209 .gdlvl container directly. Its output
contains a static-camera screen made of individually coloured, scaled blocks.
A Color Trigger is only emitted when a pixel colour differs from the preceding
sampled frame.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import html
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageSequence


MAX_DURATION_SECONDS = 10.0
MAX_COLOR_CHANNEL = 999
COLOR_CHANNEL_START = 100
STATIC_CAMERA_TRIGGER_ID = 1914
CAMERA_ZOOM_TRIGGER_ID = 1913
COLOR_TRIGGER_ID = 899
# Object 211 is the exact one-cell, fully white block from the supplied
# Unnamed 17 Vanilla export. Its 155,1 setting is preserved verbatim.
PIXEL_BLOCK_ID = 211
PIXEL_OBJECT_PROPERTIES = {155: 1}
H_BLOCK_ID = 1859
STATIC_TARGET_GROUP = 1
# The 2.2 ``Edit Group -> Extra -> Hide`` checkbox is stored as property 135.
# It keeps the camera anchor visible in the editor but permanently invisible
# during gameplay.
HIDE_PROPERTY = 135
TRIGGER_UNITS_PER_SECOND = 300.0
DEFAULT_CUSTOM_SONG_ID = 1_600_001

# This is a complete, zero-object Vanilla 2.209 level-start string. It uses
# no internal audio track; the outer level metadata uses a verified-empty
# Newgrounds custom song ID. It also has black background/ground/line channels.
LEVEL_START = (
    "kS38,"
    "1_0_2_0_3_0_11_255_12_255_13_255_4_-1_6_1000_7_1_15_1_18_0_8_1|"
    "1_0_2_0_3_0_11_255_12_255_13_255_4_-1_6_1001_7_1_15_1_18_0_8_1|"
    "1_0_2_0_3_0_11_255_12_255_13_255_4_-1_6_1009_7_1_15_1_18_0_8_1|"
    "1_0_2_0_3_0_11_255_12_255_13_255_4_-1_6_1002_5_1_7_1_15_1_18_0_8_1|"
    "1_0_2_0_3_0_11_255_12_255_13_255_4_-1_6_1004_7_1_15_1_18_0_8_1|"
    "1_40_2_125_3_255_11_255_12_255_13_255_4_-1_6_1013_7_1_15_1_18_0_8_1|"
    "1_40_2_125_3_255_11_255_12_255_13_255_4_-1_6_1014_7_1_15_1_18_0_8_1|"
    "1_0_2_125_3_255_11_255_12_255_13_255_4_-1_6_1005_5_1_7_1_15_1_18_0_8_1|"
    "1_125_2_0_3_255_11_255_12_255_13_255_4_-1_6_1006_5_1_7_1_18_0_8_1|,"
    "kA1,0,kA13,0,kA15,0,kA16,0,kA14,,kA6,0,kA7,0,kA25,0,kA17,0,kA18,0,"
    "kS39,0,kA2,0,kA3,0,kA8,0,kA4,0,kA9,0,kA10,0,kA22,0,kA23,0,kA24,0,"
    "kA27,1,kA40,1,kA57,1,kA58,1,kA48,1,kA41,1,kA42,1,kA63,0,kA29,0,"
    "kA31,1,kA32,1,kA36,0,kA43,0,kA44,0,kA45,1,kA46,0,kA47,0,kA33,1,"
    "kA34,1,kA35,0,kA37,1,kA38,1,kA39,1,kA19,0,kA26,0,kA20,0,kA21,0,"
    "kA49,0,kA50,0,kA51,0,kA52,0,kA53,,kA54,0,,,,,,,kA11,0"
)


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    frame_count: int
    fps: float
    is_gif: bool = False


def decode_urlsafe_gzip_base64(value: str) -> str:
    """Decode Geometry Dash's padded URL-safe Base64 GZIP representation."""
    normalized = value.strip().replace("-", "+").replace("_", "/")
    normalized += "=" * (-len(normalized) % 4)
    return gzip.decompress(base64.b64decode(normalized)).decode("utf-8")


def encode_urlsafe_gzip_base64(value: str) -> str:
    """Encode exactly like Vanilla's .gdlvl Base64 alphabet: '-' and '_'."""
    compressed = gzip.compress(value.encode("utf-8"), mtime=0)
    return base64.b64encode(compressed).decode("ascii").replace("+", "-").replace("/", "_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Geometry Dash 2.209 .gdlvl from a video or GIF on a static-camera pixel screen."
    )
    parser.add_argument("video", type=Path, help="Input video (maximum 10 seconds) or looping GIF.")
    parser.add_argument("output", type=Path, help="Output .gdlvl file.")
    parser.add_argument("--name", default="Video Screen", help="Name stored in the exported level.")
    parser.add_argument(
        "--nolimit",
        action="store_true",
        help="Use the input's real duration. GIFs play once instead of looping; long outputs can be very large.",
    )
    parser.add_argument("--width", type=int, default=32, help="Pixel columns (default: 32).")
    parser.add_argument("--height", type=int, default=21, help="Pixel rows (default: 21).")
    parser.add_argument("--fps", type=float, default=8.0, help="Video frame rate in GD (default: 8).")
    parser.add_argument(
        "--pixel-size",
        type=float,
        default=30.0,
        help="Distance between pixels in editor units (default: 30).",
    )
    parser.add_argument(
        "--screen-x",
        type=float,
        default=1200.0,
        help="Horizontal editor position of the screen center (default: 1200).",
    )
    parser.add_argument(
        "--screen-y",
        type=float,
        default=600.0,
        help="Vertical editor position of the screen center (default: 600).",
    )
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_video_info(video_path: Path, no_limit: bool) -> VideoInfo:
    if video_path.suffix.lower() == ".gif":
        return read_gif_info(video_path, no_limit)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        require(frame_count > 0, "The video contains no readable frames.")
        require(fps > 0, "The video's frame rate could not be read.")
        return VideoInfo(duration=frame_count / fps, frame_count=frame_count, fps=fps)
    finally:
        capture.release()


def read_gif_info(gif_path: Path, no_limit: bool) -> VideoInfo:
    """Return GIF metadata, optionally keeping its real duration for --nolimit."""
    try:
        with Image.open(gif_path) as image:
            durations = [max(int(frame.info.get("duration", 0)), 10) for frame in ImageSequence.Iterator(image)]
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot open GIF: {gif_path}") from error
    require(durations, "The GIF contains no readable frames.")
    source_duration = sum(durations) / 1000.0
    return VideoInfo(
        duration=source_duration if no_limit else MAX_DURATION_SECONDS,
        frame_count=len(durations),
        fps=len(durations) / source_duration,
        is_gif=True,
    )


def sample_video(video_path: Path, width: int, height: int, output_fps: float, duration: float) -> list:
    """Return RGB frames sampled at the requested GD playback frame rate."""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    target_count = max(1, math.ceil(duration * output_fps))
    sampled = []
    last_frame = None
    try:
        for index in range(target_count):
            timestamp_ms = min((index / output_fps) * 1000.0, max(duration * 1000.0 - 1.0, 0.0))
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
            ok, frame = capture.read()
            if not ok:
                if last_frame is None:
                    raise ValueError(f"Could not decode video frame {index}.")
                frame = last_frame
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            last_frame = frame
            # OpenCV is BGR; GD Color Triggers store RGB.
            sampled.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()
    return sampled


def sample_gif(
    gif_path: Path,
    width: int,
    height: int,
    output_fps: float,
    output_duration: float,
) -> list:
    """Sample a GIF, looping only when the requested output exceeds its duration."""
    try:
        with Image.open(gif_path) as image:
            source_frames: list = []
            frame_end_times: list[float] = []
            elapsed_ms = 0
            for source_frame in ImageSequence.Iterator(image):
                # GIF writers sometimes store 0 ms; GD needs a meaningful frame.
                elapsed_ms += max(int(source_frame.info.get("duration", 0)), 10)
                rgb = cv2.resize(
                    np.array(source_frame.convert("RGB")),
                    (width, height),
                    interpolation=cv2.INTER_AREA,
                )
                source_frames.append(rgb)
                frame_end_times.append(elapsed_ms / 1000.0)
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot decode GIF: {gif_path}") from error

    require(source_frames and frame_end_times[-1] > 0, "The GIF contains no usable animation frames.")
    source_duration = frame_end_times[-1]
    sampled = []
    target_count = max(1, math.ceil(output_duration * output_fps))
    for index in range(target_count):
        time_in_loop = (index / output_fps) % source_duration
        source_index = next(
            frame_index for frame_index, frame_end in enumerate(frame_end_times) if time_in_loop < frame_end
        )
        sampled.append(source_frames[source_index])
    return sampled


def object_string(object_id: int, x: float, y: float, properties: dict[int, object] | None = None) -> str:
    values: list[str] = ["1", str(object_id), "2", format_number(x), "3", format_number(y)]
    for key, value in (properties or {}).items():
        values.extend([str(key), format_number(value)])
    return ",".join(values)


def format_number(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def build_outer_xml(name: str, level_payload: str, object_count: int) -> str:
    """Build the fixed local-level plist accepted by Vanilla 2.209 imports."""
    escaped_name = html.escape(name, quote=False)
    return (
        '<?xml version="1.0"?><plist version="1.0" gjver="2.0"><dict>'
        '<k>kCEK</k><i>4</i>'
        f'<k>k2</k><s>{escaped_name}</s>'
        f'<k>k4</k><s>{level_payload}</s>'
        '<k>k101</k><s>0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0</s>'
        '<k>k13</k><t /><k>k21</k><i>2</i><k>k80</k><i>8</i>'
        f'<k>k45</k><i>{DEFAULT_CUSTOM_SONG_ID}</i>'
        '<k>k156</k><s>1,1,0,0,0,0,0,0,0,527,0,0,0,0,0,0,0,0,7,1,1793530728,0,0</s>'
        f'<k>k50</k><i>51</i><k>k48</k><i>{object_count}</i>'
        '<k>kI1</k><r>30</r><k>kI2</k><r>96</r><k>kI3</k><r>1</r><k>kI4</k><i>1</i>'
        '<k>kI6</k><d><k>0</k><s>1</s><k>1</k><s>0</s><k>2</k><s>0</s>'
        '<k>3</k><s>0</s><k>4</k><s>0</s><k>5</k><s>0</s><k>6</k><s>0</s>'
        '<k>7</k><s>0</s><k>8</k><s>0</s><k>9</k><s>0</s><k>10</k><s>0</s>'
        '<k>11</k><s>0</s><k>12</k><s>0</s><k>13</k><s>0</s></d></dict></plist>'
    )


def build_objects(args: argparse.Namespace, frames: list) -> tuple[list[str], int]:
    objects: list[str] = []
    screen_pixel_count = args.width * args.height
    pixel_scale = args.pixel_size / 30.0
    screen_left = args.screen_x - ((args.width - 1) * args.pixel_size / 2.0)
    screen_top = args.screen_y + ((args.height - 1) * args.pixel_size / 2.0)

    # Each visible block has its own color channel.
    for row in range(args.height):
        for column in range(args.width):
            pixel_index = row * args.width + column
            channel = COLOR_CHANNEL_START + pixel_index
            properties: dict[int, object] = {
                **PIXEL_OBJECT_PROPERTIES,
                21: channel,
                32: pixel_scale,
                24: 7,
                25: pixel_index,
            }
            objects.append(
                object_string(
                    PIXEL_BLOCK_ID,
                    screen_left + column * args.pixel_size,
                    screen_top - row * args.pixel_size,
                    properties,
                )
            )

    # A separate exact-center anchor is essential: it is in Group 1 and has
    # Extra -> Hide enabled, so it never becomes a visible video pixel.
    objects.append(
        object_string(
            PIXEL_BLOCK_ID,
            args.screen_x,
            args.screen_y,
            {**PIXEL_OBJECT_PROPERTIES, 57: STATIC_TARGET_GROUP, HIDE_PROPERTY: 1},
        )
    )

    # The zoom trigger sits directly above Static Camera, before the start
    # line. Zoom 0.5 shows the whole enlarged screen instead of cropping it.
    static_trigger_x = -30.0
    objects.append(
        object_string(
            CAMERA_ZOOM_TRIGGER_ID,
            static_trigger_x,
            75.0,
            {10: 0, 371: 0.5},
        )
    )

    # Key 71 is Static Camera's target group, and duration zero frames the
    # camera immediately around the hidden Group 1 anchor.
    objects.append(
        object_string(
            STATIC_CAMERA_TRIGGER_ID,
            static_trigger_x,
            45.0,
            {10: 0, 71: STATIC_TARGET_GROUP},
        )
    )

    # The first frame initializes every pixel. Later frames emit a trigger only
    # where that pixel changed, which removes redundant triggers for stable
    # areas such as a black video border.
    first_frame_x = 120.0
    color_trigger_count = 0
    for frame_index, frame in enumerate(frames):
        trigger_x = first_frame_x + frame_index * (TRIGGER_UNITS_PER_SECOND / args.fps)
        for row in range(args.height):
            for column in range(args.width):
                if frame_index > 0 and (frame[row, column] == frames[frame_index - 1][row, column]).all():
                    continue
                pixel_index = row * args.width + column
                red, green, blue = (int(value) for value in frame[row, column])
                objects.append(
                    object_string(
                        COLOR_TRIGGER_ID,
                        trigger_x,
                        15.0,
                        {7: red, 8: green, 9: blue, 10: 0, 23: COLOR_CHANNEL_START + pixel_index},
                    )
                )
                color_trigger_count += 1

    # Safe runway: H Blocks (ID 1859) act as a floor and an overhead safety
    # rail. A jumping cube/robot/spider may hit the rail but does not take
    # overhead damage, so it can keep activating the whole video.
    video_end_x = first_frame_x + len(frames) * (TRIGGER_UNITS_PER_SECOND / args.fps)
    for x in range(0, math.ceil(video_end_x + 240), 30):
        objects.append(object_string(H_BLOCK_ID, x, 45, {21: 1004}))
        objects.append(object_string(H_BLOCK_ID, x, 135, {21: 1004}))

    return objects, color_trigger_count


def create_level(args: argparse.Namespace) -> None:
    require(args.video.is_file(), f"Video does not exist: {args.video}")
    require(args.output.suffix.lower() == ".gdlvl", "Output file must have the .gdlvl extension.")
    require(args.width > 0 and args.height > 0, "Width and height must be positive.")
    require(args.fps > 0, "Output FPS must be positive.")
    require(args.pixel_size > 0, "Pixel size must be positive.")
    require(COLOR_CHANNEL_START + args.width * args.height - 1 <= MAX_COLOR_CHANNEL,
            f"This resolution needs {args.width * args.height} channels; maximum is "
            f"{MAX_COLOR_CHANNEL - COLOR_CHANNEL_START + 1} with the current channel range.")

    info = read_video_info(args.video, args.nolimit)
    require(args.nolimit or info.is_gif or info.duration <= MAX_DURATION_SECONDS + 0.02,
            f"Video is {info.duration:.2f} seconds long; the limit is {MAX_DURATION_SECONDS:.0f} seconds.")

    frames = (
        sample_gif(args.video, args.width, args.height, args.fps, info.duration)
        if info.is_gif
        else sample_video(args.video, args.width, args.height, args.fps, info.duration)
    )
    objects, color_trigger_count = build_objects(args, frames)
    inner_level = LEVEL_START + ";" + ";".join(objects) + ";"
    outer_xml = build_outer_xml(args.name, encode_urlsafe_gzip_base64(inner_level), len(objects))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encode_urlsafe_gzip_base64(outer_xml), encoding="utf-8")

    # Decode the written result again so a broken container never gets handed off.
    checked_xml = decode_urlsafe_gzip_base64(args.output.read_text(encoding="utf-8"))
    checked_payload = re.search(r"<k>k4</k><s>([^<]+)</s>", checked_xml)
    if not checked_payload:
        raise RuntimeError("Validation failed: output has no k4 payload.")
    checked_inner = decode_urlsafe_gzip_base64(checked_payload.group(1))
    checked_count = len([item for item in checked_inner.split(";")[1:] if item])
    if checked_count != len(objects):
        raise RuntimeError(f"Validation failed: expected {len(objects)} objects, decoded {checked_count}.")
    if "+" in args.output.read_text(encoding="utf-8") or "/" in args.output.read_text(encoding="utf-8"):
        raise RuntimeError("Validation failed: output is not URL-safe Base64.")

    print(f"Created: {args.output}")
    source_kind = "GIF single pass" if info.is_gif and args.nolimit else "GIF loop" if info.is_gif else "Input"
    print(f"{source_kind}: {info.duration:.2f} seconds, sampled at {args.fps:g} FPS ({len(frames)} frames)")
    print(f"Screen: {args.width}x{args.height} = {args.width * args.height} independent color channels")
    print(f"Color Triggers: {color_trigger_count} (unchanged pixels reuse the previous frame's color)")
    print(f"Objects: {len(objects)}")


def main() -> int:
    try:
        create_level(parse_args())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
