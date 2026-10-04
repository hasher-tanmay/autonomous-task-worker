# Real-model demo

[Watch the captioned MP4](demo.mp4)

This silent screencast records the current Harbor web app using OpenAI gpt-4.1-mini. It shows actual browser work and saved invoice records in the synthetic company portal. Short captions describe each workflow.

| Time | Scene |
|---|---|
| 0:01 | Autonomy and execution |
| 0:26 | Verification: saved row and browser evidence |
| 0:34 | Generalization: a read-only task |
| 0:54 | Generalization: multiple documents |
| 1:16 | Product thinking: approval before a high-value write |
| 1:43 | Product thinking: ask instead of guessing |

The app focuses on tasks, invoices, activity and the browser view. Architecture and evaluation details are in the [README](../README.md) and [evaluation report](EVALUATION.md), outside the product interface. Failure injection remains available through the integration tests and model evaluation script.

To reproduce, start the app with your own ignored `.env`, install `imageio-ffmpeg`, then run `python scripts/record_demo.py --mode model`. The app must be running locally without `--share` unless public model use was explicitly enabled.

The public Gradio relay timed out from the current network. Use the recording and local setup as the reproducible demo.
