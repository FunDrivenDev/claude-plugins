---
name: local-llm-advisor
disable-model-invocation: true
description: Recommend the best local-LLM setup for coding agents on the machine you run it on — runtime, harness, models per role — from fresh benchmarks and this machine's specs.
---

# Local LLM advisor

Advise on one concrete setup for running open-weight models locally on **this** machine, for coding
agents: task definition and specs, implementation, review, several agents at once. Every fact comes
from this run: the machine is probed, the model and runtime landscape is researched fresh. Knowledge
from training is a list of names to check, never an answer.

Invocation arguments, when given, narrow the scope (a use case, a model to evaluate, "laptop only").

## Steps

1. **Probe.** Run `bash scripts/probe.sh` from this skill's directory. When `llmfit` is installed, also
   run `llmfit update`. Look up the chip's memory bandwidth from the vendor's spec page (the probe
   can't read it). Done when you know: chip, total memory, GPU-usable memory, bandwidth, free disk,
   runtimes and models already installed, servers already running, battery or desktop.
2. **Research.** Search the web for the current state, dated within the last 3 months where possible:
   - **Models**: the newest open-weight release of each lab (Qwen, DeepSeek, Z.ai GLM, Moonshot Kimi,
     MiniMax, Google Gemma, Mistral, NVIDIA Nemotron, OpenAI gpt-oss, Poolside Laguna, Meta, plus any
     newcomer ranking on the boards below). Shortlist those whose ~4-bit weights fit the memory budget
     (criterion 1) and keep the best that don't fit as upgrade references.
   - **Benchmarks** for every shortlisted model, from the sources in criterion 3.
   - **Runtimes**: latest release notes of Ollama, LM Studio, llama.cpp, MLX servers (oMLX, mlx-lm) on
     Mac, vLLM / SGLang on NVIDIA: engine per architecture, parallel requests, prompt caching,
     OpenAI / Anthropic API support, support for each shortlisted model's architecture.
   - **Harnesses**: OpenCode, Claude Code against a local endpoint, Aider, Cline, and any rising one;
     subagents and per-agent model choice.

   With llmfit, use `llmfit info <model>` and `llmfit concurrency <model> --context 65536` for fit,
   speed and session estimates; its `recommend` ranking favours community fine-tunes, so it never
   picks the model. Done when every shortlisted model has a fit, a speed estimate, at least one
   independent score or a note that none exists, and a runtime that supports it on this machine.
3. **Clarify.** Ask only what changes the recommendation and can't be read from the machine or the
   arguments, in one `AskUserQuestion` call (at most 3 questions). Typical: is the machine dedicated to
   inference or shared with heavy dev work; is a cloud frontier model available for planning and final
   review; licence constraints. Otherwise state the assumption in the report and move on.
4. **Decide.** Apply every criterion below to the shortlist, then pick one runtime, one harness, and a
   model per role. Done when each choice names the criterion that decided it.
5. **Report.** Deliver the report in the chat, in the format below. When the user's instructions name
   a folder for reports, also save it there.

## Criteria

The user's priorities, in order: simple, maintainable, trustworthy, low overhead, then the best
quality per unit of memory and bandwidth.

1. **Fit.** Weights at the chosen quant + KV cache for every concurrent agent at 64k context + OS and
   apps headroom ≤ GPU-usable memory. On macOS the GPU gets roughly 2/3 (≤36 GB) to 3/4 of RAM by
   default; `iogpu.wired_limit_mb` raises it. Keep 4-bit as the floor for agent work; 2–3-bit breaks
   tool calling first.
2. **Speed.** Decode ≈ 0.6 × bandwidth ÷ bytes read per token (active params × bits ÷ 8). Interactive
   workers need ≥ 20 tok/s; a background reviewer can live with ≥ 8. Prefill is the Mac's weak point:
   favour runtimes with prompt caching, and harnesses with short system prompts. Tokens per answer
   count as much as tokens per second: a terser model can finish first.
3. **Quality, independent first.** Rank on contamination-free and third-party boards (SWE-rebench,
   Artificial Analysis Coding Index, Code Arena WebDev); use vendor SWE-bench Pro and Terminal-Bench as
   secondary; treat vendor SWE-bench Verified as inflated for small models. Compare the same benchmark
   version only (Terminal-Bench 2.0 ≠ 2.1).
4. **Agent reliability.** Tool calling, instruction following and looping, from practitioner reports.
   A model that loops or refuses tools is out, whatever its scores.
5. **Concurrency.** Continuous batching in the runtime, and KV per session from criterion 1, decide
   how many agents run at once.
6. **Support.** The runtime supports the model's architecture on this OS and chip, in a release (a
   pending PR or an "experimental" label is an upgrade path, not the recommendation).
7. **Licence.** Permissive (Apache-2.0, MIT) unless the user says otherwise; flag custom terms.
8. **Stack simplicity.** Fewest moving parts that meet 1–7: one runtime, one harness with built-in
   subagents, no orchestration framework, no gateway (LiteLLM and the like) unless local and cloud
   models are mixed.

## Report format

Concise: a reader decides from it in two minutes.

1. **Verdict**: one sentence naming runtime + harness + models.
2. **Machine**: one line (chip, memory, GPU-usable memory, bandwidth, disk free).
3. **Setup**: a table with one row per role (planner / reviewer / worker / explorer): model, quant,
   memory, expected tok/s, why. Then the memory budget line (weights + KV + headroom = total), and
   the install and run commands for the chosen stack.
4. **Delegation**: which tasks these models take on this machine and which stay with a frontier model.
5. **Alternatives**: at most two, each with the trade-off that makes it second.
6. **Upgrade path**: the model or hardware step that would change the verdict, with its number.
7. **Caveats**: vendor-only scores, estimates versus measurements, experimental support.
8. **Sources**: links with their dates.
