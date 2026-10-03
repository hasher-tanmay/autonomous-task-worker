# Real-model demo

[Watch the captioned MP4](demo.mp4)

The 3 minute 21 second silent screencast records the actual Gradio app using OpenAI gpt-4.1-mini. Criterion captions explain each scene. Browser actions, form submissions, saved records and verification are real; the company portal and failures are synthetic.

| Time | Scene |
|---|---|
| 0:01 | Autonomy and execution |
| 0:20 | Reliability: observe, then retry |
| 0:27 | Verification: saved row and browser evidence |
| 0:35 | Generalization: a read-only task |
| 0:54 | Generalization: multiple documents |
| 1:18 | Product thinking: approval before a high-value write |
| 1:44 | Reliability: uncertain acknowledgement |
| 2:03 | Reliability: bounded failure |
| 2:27 | Verification: reject corrupted persistence |
| 2:44 | Product thinking: ask instead of guessing |
| 2:56 | Engineering quality and technical understanding |
| 3:12 | Measured evaluation evidence |

The video covers all eight criteria within the invoice sandbox. The architecture scene explains engineering choices and limitations; it cannot substitute for the submitter understanding the code. See [evaluation evidence](EVALUATION.md) for the ten measured model scenarios and eighteen integration checks.

To reproduce, start the app with your own ignored .env, install imageio-ffmpeg, then run python scripts/record_demo.py --mode model. The app must be running locally without --share unless public model use was explicitly enabled.

The public Gradio relay timed out from the current network. Use the recording and local setup as the reproducible submission demo.
