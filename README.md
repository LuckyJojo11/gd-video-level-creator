# GD Video To Level

`GD Video To Level` converts a video or animated GIF into a Vanilla Geometry Dash 2.209 `.gdlvl` file. The generated level displays the input on a large pixel screen, using one independent colour channel per on-screen pixel and a sequence of instant Color Triggers.

The tool writes the `.gdlvl` container directly. It does not require Geode, a level template, a running copy of Geometry Dash, or an existing exported level.

## Requirements

- Windows, macOS, or Linux
- Python 3.10 or newer
- Geometry Dash 2.209 for importing the resulting `.gdlvl`

Install the Python packages once from this folder:

```powershell
python -m pip install -r requirements.txt
```

## Quick start

```powershell
python .\video_to_gdlvl.py .\my-video.mp4 .\video-screen.gdlvl
```

The generated `video-screen.gdlvl` can be imported in Geometry Dash through **My Levels → Import**.

The batch file provides the same command:

```powershell
.\run_video_to_gdlvl.bat .\my-video.mp4 .\video-screen.gdlvl
```

## Supported input

The first positional argument accepts normal video files supported by OpenCV, such as `.mp4`, `.avi`, `.mov`, and `.webm`, plus animated `.gif` files.

By default, normal videos longer than ten seconds are rejected. GIFs are allowed at any source length: they loop until the exported level reaches ten seconds, then stop. This means a two-second GIF plays five times, while a twelve-second GIF uses only its first ten seconds.

## `--nolimit`: keep the real duration

Add `--nolimit` to use the actual duration of the input instead of the ten-second default:

```powershell
python .\video_to_gdlvl.py .\long-video.mp4 .\long-screen.gdlvl --nolimit
```

For normal videos, the whole video is sampled. For GIFs, `--nolimit` disables looping: the GIF plays exactly once and ends at its real final frame.

There is intentionally no automatic object-count cap in this mode. A long clip, high FPS, or high resolution can create a very large level and may affect loading or editor performance.

## Command-line options

```text
video_to_gdlvl.py INPUT OUTPUT [options]
```

| Option | Default | Meaning |
| --- | ---: | --- |
| `--name NAME` | `Video Screen` | Level name shown in My Levels. |
| `--nolimit` | off | Use the input's real duration. GIFs play once instead of looping. |
| `--width PIXELS` | `32` | Horizontal screen resolution. |
| `--height PIXELS` | `21` | Vertical screen resolution. |
| `--fps FPS` | `8` | Number of video samples per second. |
| `--pixel-size UNITS` | `30` | Grid distance between pixels. `30` is one editor cell. |
| `--screen-x X` | `1200` | Screen centre X position in editor units. |
| `--screen-y Y` | `600` | Screen centre Y position in editor units. |

Example for a lower-object-count preview:

```powershell
python .\video_to_gdlvl.py .\clip.gif .\preview.gdlvl --width 16 --height 9 --fps 6
```

Example for a 10-second, 36×24 screen:

```powershell
python .\video_to_gdlvl.py .\clip.mp4 .\high-quality.gdlvl --width 36 --height 24 --fps 8
```

## How the generated level works

### Pixel screen

Every visible pixel is object `211`, the single-cell fully white block used in the supplied Vanilla reference export. Each pixel receives its own colour channel, starting at channel 100. The tool supports at most 900 pixels (`width × height`) because the selected channel range ends at 999.

### Trigger optimisation

The first sampled frame initializes every pixel. Afterwards, a Color Trigger is emitted only for a pixel whose RGB value changed relative to the preceding sampled frame. Static black borders and still backgrounds therefore generate no repeated triggers, while the visible resolution stays unchanged.

The maximum trigger count for a changing input is approximately:

```text
width × height × sampled frames
```

Real clips often use fewer triggers because of the per-pixel change detection.

### Camera and gameplay safety

- The screen centre is at `X=1200`, `Y=600` by default.
- A separate object at the exact centre has Group ID `1` and `Extra → Hide` enabled.
- A Zoom Camera Trigger (`1913`) at `X=-30`, `Y=75` sets zoom to `0.5` instantly.
- A Static Camera Trigger (`1914`) at `X=-30`, `Y=45` targets Group ID `1` instantly.
- H Blocks (`1859`) form a floor and overhead safety rail so jumps do not kill the player while the trigger sequence runs.

### Silent black level base

The generated level uses Newgrounds custom-song ID `1600001` by default. This ID was checked as unavailable (a Newgrounds `404` response), so it does not point to a playable Newgrounds track. Background, ground, second ground, line, and default object colours are initialized as black. No template data is used.

## Important limits and recommendations

- Default mode produces ten seconds of output.
- `--nolimit` may create many thousands of additional triggers for long inputs.
- A resolution above 900 pixels is rejected because every pixel needs a distinct colour channel.
- Use `--width 16 --height 9 --fps 6` first to verify a new source clip quickly.
- Use lower FPS before reducing resolution when the movement is choppy.
- Use lower resolution before reducing FPS when the picture is unclear.
- Videos with large unchanged areas are especially efficient because unchanged pixels do not need new triggers.

## Troubleshooting

### `Cannot open video` or `Cannot open GIF`

Check the input path, then verify that the video plays locally. Reinstall the dependencies with:

```powershell
python -m pip install --upgrade -r requirements.txt
```

### The level is too large or loads slowly

Reduce `--width`, `--height`, or `--fps`. Avoid `--nolimit` for long clips until a short test export looks correct.

### The picture is too small or too large

Change `--pixel-size` to alter the physical size of the pixel grid. Change the generated Zoom Trigger in the Python source only if the desired camera framing differs from the default zoom `0.5`.

### Geometry Dash does not import the file

Ensure that the output still has the `.gdlvl` extension and import the exact generated file through **My Levels → Import**. Do not manually re-encode, unzip, or edit its Base64 content.
