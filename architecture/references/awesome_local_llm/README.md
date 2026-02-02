# Awesome local LLM <img src="https://awesome.re/badge.svg"/>
A curated list of awesome platforms, tools, practices and resources that helps run LLMs locally

## Table of Contents

- [Inference platforms](#inference-platforms)
- [Inference engines](#inference-engines)
- [User Interfaces](#user-interfaces)
- [Large Language Models](#large-language-models)
  - [Explorers, Benchmarks, Leaderboards](#explorers-benchmarks-leaderboards)
  - [Model providers](#model-providers)
  - [Specific models](#specific-models)
    - [General purpose](#general-purpose)
    - [Coding](#coding)
    - [Multimodal](#multimodal)
    - [Image](#image)
    - [Audio](#audio)
    - [Safeguards](#safeguards)
    - [Miscellaneous](#miscellaneous)
- [Tools](#tools)
  - [Models](#models)
  - [Agent Frameworks](#agent-frameworks)
  - [Model Context Protocol](#model-context-protocol)
  - [Retrieval-Augmented Generation](#retrieval-augmented-generation)
  - [Coding Agents](#coding-agents)
  - [Computer Use](#computer-use)
  - [Browser Automation](#browser-automation)
  - [Memory Management](#memory-management)
  - [Testing, Evaluation, and Observability](#testing-evaluation-and-observability)
  - [Research](#research)
  - [Training and Fine-tuning](#training-and-fine-tuning)
  - [Miscellaneous](#miscellaneous-1)
- [Hardware](#hardware)
- [Tutorials](#tutorials)
  - [Models](#models-1)
  - [Prompt Engineering](#prompt-engineering)
  - [Context Engineering](#context-engineering)
  - [Inference](#inference)
  - [Agents](#agents)
  - [Retrieval-Augmented Generation](#retrieval-augmented-generation-1)
  - [Miscellaneous](#miscellaneous-2)
- [Communities](#communities)

## Inference platforms

- [LM Studio](https://lmstudio.ai/) - discover, download and run local LLMs
- [jan](https://github.com/menloresearch/jan) - an open source alternative to ChatGPT that runs 100% offline on your computer
- [LocalAI](https://github.com/mudler/LocalAI) -  the free, open-source alternative to OpenAI, Claude and others
- [ChatBox](https://github.com/ChatBoxAI/ChatBox) - user-friendly desktop client app for AI models/LLMs
- [lemonade](https://github.com/lemonade-sdk/lemonade) - a local LLM server with GPU and NPU Acceleration

[Back to Table of Contents](#table-of-contents)

## Inference engines

- [ollama](https://github.com/ollama/ollama) - get up and running with LLMs
- [llama.cpp](https://github.com/ggml-org/llama.cpp) - LLM inference in C/C++
- [vllm](https://github.com/vllm-project/vllm) - a high-throughput and memory-efficient inference and serving engine for LLMs
- [exo](https://github.com/exo-explore/exo) - run your own AI cluster at home with everyday devices
- [BitNet](https://github.com/microsoft/BitNet) - official inference framework for 1-bit LLMs
- [sglang](https://github.com/sgl-project/sglang) - a fast serving framework for large language models and vision language models
- [Nano-vLLM](https://github.com/GeeeekExplorer/nano-vllm) - a lightweight vLLM implementation built from scratch
- [koboldcpp](https://github.com/LostRuins/koboldcpp) - run GGUF models easily with a KoboldAI UI
- [gpustack](https://github.com/gpustack/gpustack) - simple, scalable AI model deployment on GPU clusters
- [mlx-lm](https://github.com/ml-explore/mlx-lm) - generate text and fine-tune large language models on Apple silicon with MLX
- [distributed-llama](https://github.com/b4rtaz/distributed-llama) - connect home devices into a powerful cluster to accelerate LLM inference
- [ik_llama.cpp](https://github.com/ikawrakow/ik_llama.cpp) - llama.cpp fork with additional SOTA quants and improved performance
- [mini-sglang](https://github.com/sgl-project/mini-sglang) - a lightweight yet high-performance inference framework for Large Language Models
- [FastFlowLM](https://github.com/FastFlowLM/FastFlowLM) - run LLMs on AMD Ryzen AI NPUs
- [vllm-gfx906](https://github.com/nlzy/vllm-gfx906) - vLLM for AMD gfx906 GPUs, e.g. Radeon VII / MI50 / MI60
- [llm-scaler](https://github.com/intel/llm-scaler) - run LLMs on Intel Arc Pro B60 GPUs

[Back to Table of Contents](#table-of-contents)

## User Interfaces

- [Open WebUI](https://github.com/open-webui/open-webui) - User-friendly AI Interface (Supports Ollama, OpenAI API, ...)
- [Lobe Chat](https://github.com/lobehub/lobe-chat) - an open-source, modern design AI chat framework
- [Text generation web UI](https://github.com/oobabooga/text-generation-webui) - LLM UI with advanced features, easy setup, and multiple backend support
- [SillyTavern](https://github.com/SillyTavern/SillyTavern) - LLM Frontend for Power Users
- [Page Assist](https://github.com/n4ze3m/page-assist) - Use your locally running AI models to assist you in your web browsing

[Back to Table of Contents](#table-of-contents)

## Large Language Models

### Explorers, Benchmarks, Leaderboards

- [AI Models & API Providers Analysis](https://artificialanalysis.ai/) - understand the AI landscape to choose the best model and provider for your use case
- [LLM Explorer](https://llm-explorer.com/) - explore list of the open-source LLM models
- [Dubesor LLM Benchmark table](https://dubesor.de/benchtable) - small-scale manual performance comparison benchmark
- [oobabooga benchmark](https://oobabooga.github.io/benchmark.html) - a list sorted by size (on disk) for each score

[Back to Table of Contents](#table-of-contents)

### Model providers

- [Qwen](https://huggingface.co/Qwen) - powered by Alibaba Cloud
- [Mistral AI](https://huggingface.co/mistralai) - a pioneering French artificial intelligence startup
- [Tencent](https://huggingface.co/tencent) - a profile of a Chinese multinational technology conglomerate and holding company
- [Unsloth AI](https://huggingface.co/unsloth) - focusing on making AI more accessible to everyone (GGUFs etc.)
- [bartowski](https://huggingface.co/bartowski) - providing GGUF versions of popular LLMs
- [Beijing Academy of Artificial Intelligence](https://huggingface.co/BAAI) - a private non-profit organization engaged in AI research and development
- [Open Thoughts](https://huggingface.co/open-thoughts) - a team of researchers and engineers curating the best open reasoning datasets

[Back to Table of Contents](#table-of-contents)

### Specific models

#### General purpose

- [Qwen3-Next](https://huggingface.co/collections/Qwen/qwen3-next-68c25fd6838e585db8eeea9d) - a collection of the latest generation Qwen LLMs
- [Gemma 3](https://huggingface.co/collections/google/gemma-3-release-67c6c6f89c4f76621268bb6d) - a family of lightweight, state-of-the-art open models from Google, built from the same research and technology used to create the Gemini models
- [gpt-oss](https://huggingface.co/collections/openai/gpt-oss-68911959590a1634ba11c7a4) - a collection of open-weight models from OpenAI, designed for powerful reasoning, agentic tasks, and versatile developer use cases
- [Ministral 3](https://huggingface.co/collections/mistralai/ministral-3) - a collection of edge models, with base, instruct and reasoning variants, in 3 different sizes: 3B, 8B and 14B, all with vision capabilities
- [Hunyuan](https://huggingface.co/collections/tencent/hunyuan-dense-model-6890632cda26b19119c9c5e7) - a collection of Tencent's open-source efficient LLMs designed for versatile deployment across diverse computational environments
- [Phi-4](https://huggingface.co/collections/microsoft/phi-4) - a family of small language, multi-modal and reasoning models from Microsoft
- [NVIDIA Nemotron v3](https://huggingface.co/collections/nvidia/nvidia-nemotron-v3) - a family of open models from NVIDIA with open weights, training data and recipes, delivering leading efficiency and accuracy for building specialized AI agents
- [Llama Nemotron](https://huggingface.co/collections/nvidia/llama-nemotron-67d92346030a2691293f200b) - a collection of open, production-ready enterprise models from NVIDIA
- [OpenReasoning-Nemotron](https://huggingface.co/collections/nvidia/openreasoning-nemotron-687730dae0170059860f1f01) - a collection of models from NVIDIA, trained on 5M reasoning traces for math, code and science
- [Granite 4.0](https://huggingface.co/collections/ibm-granite/granite-40-language-models-6811a18b820ef362d9e5a82c) - a collection of lightweight, state-of-the-art open foundation models from IBM that natively support multilingual capabilities, a wide range of coding tasks—including fill-in-the-middle (FIM) code completion—retrieval-augmented generation (RAG), tool usage and structured JSON output
- [EXAONE-4.0](https://huggingface.co/collections/LGAI-EXAONE/exaone-40-686b2e0069800c835ed48375) - a collection of LLMs from LG AI Research, integrating non-reasoning and reasoning modes
- [ERNIE 4.5](https://huggingface.co/collections/baidu/ernie-45-6861cd4c9be84540645f35c9) - a collection of large-scale multimodal models from Baidu
- [Seed-OSS](https://huggingface.co/collections/ByteDance-Seed/seed-oss-68a609f4201e788db05b5dcd) - a collection of LLMs developed by ByteDance's Seed Team, designed for powerful long-context, reasoning, agent and general capabilities, and versatile developer-friendly features

[Back to Table of Contents](#table-of-contents)

#### Coding

- [Qwen3-Coder](https://huggingface.co/collections/Qwen/qwen3-coder-687fc861e53c939e52d52d10) - a collection of the Qwen's most agentic code models to date
- [Devstral 2](https://huggingface.co/collections/mistralai/devstral-2) - a couple of agentic LLMs for software engineering tasks, excelling at using tools to explore codebases, edit multiple files, and power SWE Agents
- [GLM-4.7](https://huggingface.co/collections/zai-org/glm-47) - a collection of agentic, reasoning and coding (ARC) foundation models
- [MiniMax-M2.1](https://huggingface.co/MiniMaxAI/MiniMax-M2.1) - a SOTA model for real-world dev & agents
- [NousCoder-14B](https://huggingface.co/NousResearch/NousCoder-14B) - a competitive programming model post-trained on Qwen3-14B via reinforcement learning
- [FrogBoss-32B-2510](https://huggingface.co/microsoft/FrogBoss-32B-2510) & [FrogMini-14B-2510](https://huggingface.co/microsoft/FrogMini-14B-2510) - coding agents specialized in fixing bugs in code obtained by fine-tuning a Qwen3-32B and Qwen3-14B language model, respectively, on debugging trajectories generated by Claude Sonnet 4 within the BugPilot framework
- [Mellum-4b-base](https://huggingface.co/JetBrains/Mellum-4b-base) - an LLM from JetBrains, optimized for code-related tasks
- [Stable-DiffCoder](https://huggingface.co/collections/ByteDance-Seed/stable-diffcoder) - a strong code diffusion large language model

[Back to Table of Contents](#table-of-contents)

#### Multimodal

- [Qwen3-Omni](https://huggingface.co/collections/Qwen/qwen3-omni-68d100a86cd0906843ceccbe) - a collection of the natively end-to-end multilingual omni-modal foundation models from Qwen
- [GLM-4.6V](https://huggingface.co/collections/zai-org/glm-46v) - a collection of open source multimodal models with native tool use from Zhipu AI

[Back to Table of Contents](#table-of-contents)

#### Image

- [Qwen-Image](https://huggingface.co/collections/Qwen/qwen-image) - a collection of models for image generation, edit and decomposition from Qwen
- [Qwen3-VL](https://huggingface.co/collections/Qwen/qwen3-vl-68d2a7c1b8a8afce4ebd2dbe) - a collection of the most powerful vision-language models in the Qwen series to date
- [GLM-Image](https://huggingface.co/zai-org/GLM-Image) - an image generation model
- [HunyuanImage-2.1](https://huggingface.co/tencent/HunyuanImage-2.1) - an efficient diffusion model for high-resolution (2K) text-to-image generation
- [Vidi](https://huggingface.co/collections/bytedance-research/vidi) - a collection of models for multimodal video understanding and creation
- [FastVLM](https://huggingface.co/collections/apple/fastvlm-68ac97b9cd5cacefdd04872e) - a collection of VLMs with efficient vision encoding from Apple
- [MiniCPM-V-4_5](https://huggingface.co/openbmb/MiniCPM-V-4_5) - a GPT-4o Level MLLM for single image, multi image and high-FPS video understanding on your phone
- [LFM2-VL](https://huggingface.co/collections/LiquidAI/lfm2-vl-68963bbc84a610f7638d5ffa) - a colection of vision-language models, designed for on-device deployment
- [ClipTagger-12b](https://huggingface.co/inference-net/ClipTagger-12b) -  a vision-language model (VLM) designed for video understanding at massive scale

[Back to Table of Contents](#table-of-contents)

#### Audio

- [Nemotron Speech](https://huggingface.co/collections/nvidia/nemotron-speech) - a collection of open, state-of-the-art, production-ready enterprise speech models from the NVIDIA Speech research team for ASR, TTS, Speaker Diarization and S2S
- [Qwen3-TTS](https://huggingface.co/collections/Qwen/qwen3-tts) - a collection of TTS models that covers 10 major languages as well as multiple dialectal voice profiles to meet global application needs
- [Voxtral-Small-24B-2507](https://huggingface.co/mistralai/Voxtral-Small-24B-2507) - an enhancement of Mistral Small 3, incorporating state-of-the-art audio input capabilities while retaining best-in-class text performance
- [chatterbox](https://huggingface.co/ResembleAI/chatterbox) - first production-grade open-source TTS model
- [VibeVoice](https://huggingface.co/collections/microsoft/vibevoice-68a2ef24a875c44be47b034f) - a collection of frontier text-to-speech models from Microsoft
- [Kitten TTS](https://huggingface.co/KittenML/models) - a collection of open-source realistic text-to-speech models designed for lightweight deployment and high-quality voice synthesis

[Back to Table of Contents](#table-of-contents)

#### Safeguards

- [gpt-oss-safeguard](https://huggingface.co/collections/openai/gpt-oss-safeguard) - a collection of safety reasoning models built-upon gpt-oss
- [Granite Guardian Models](https://huggingface.co/collections/ibm-granite/granite-guardian-models) - a collection of models created by IBM for safeguarding language models
- [Qwen3Guard](https://huggingface.co/collections/Qwen/qwen3guard-68d2729abbfae4716f3343a1) - a collection of safety moderation models built upon Qwen3
- [NemoGuard](https://huggingface.co/collections/nvidia/nemoguard) - a collection of models from NVIDIA for content safety, topic-following and security guardrails
- [AprielGuard](https://huggingface.co/ServiceNow-AI/AprielGuard) - a safeguard model designed to detect and mitigate both safety risks and security threats in LLM interactions

[Back to Table of Contents](#table-of-contents)

#### Miscellaneous

- [Jan-v1-4B](https://huggingface.co/janhq/Jan-v1-4B) - the first release in the Jan Family, designed for agentic reasoning and problem-solving within the Jan App
- [Jan-nano](https://huggingface.co/Menlo/Jan-nano) - a compact 4-billion parameter language model specifically designed and trained for deep research tasks
- [Jan-nano-128k](https://huggingface.co/Menlo/Jan-nano-128k) - an enhanced version of Jan-nano features a native 128k context window that enables deeper, more comprehensive research capabilities without the performance degradation typically associated with context extension method
- [Nemotron-Orchestrator-8B](https://huggingface.co/nvidia/Nemotron-Orchestrator-8B) - a state-of-the-art 8B orchestration model designed to solve complex, multi-turn agentic tasks by coordinating a diverse set of expert models and tools
- [Arch-Router-1.5B](https://huggingface.co/katanemo/Arch-Router-1.5B) - the fastest LLM router model that aligns to subjective usage preferences
- [Waypoint-1](https://huggingface.co/collections/Overworld/waypoint-1) - a collection of control-and-text-conditioned causal diffusion models that can generate worlds in realtime on high-end consumer hardware
- [HunyuanWorld-1](https://huggingface.co/tencent/HunyuanWorld-1) - an open-source 3D world generation model
- [Hunyuan-GameCraft-1.0](https://huggingface.co/tencent/Hunyuan-GameCraft-1.0) - a novel framework for high-dynamic interactive video generation in game environments

[Back to Table of Contents](#table-of-contents)

## Tools

### Models

- [unsloth](https://github.com/unslothai/unsloth) - fine-tuning & reinforcement learning for LLMs
- [outlines](https://github.com/dottxt-ai/outlines) - structured outputs for LLMs
- [heretic](https://github.com/p-e-w/heretic) - fully automatic censorship removal for language models
- [llama-swap](https://github.com/mostlygeek/llama-swap) - reliable model swapping for any local OpenAI compatible server - llama.cpp, vllm, etc.

[Back to Table of Contents](#table-of-contents)

### Agent Frameworks

- [AutoGPT](https://github.com/Significant-Gravitas/AutoGPT) - a powerful platform that allows you to create, deploy, and manage continuous AI agents that automate complex workflows
- [langflow](https://github.com/langflow-ai/langflow) - a powerful tool for building and deploying AI-powered agents and workflows
- [langchain](https://github.com/langchain-ai/langchain) - build context-aware reasoning applications
- [autogen](https://github.com/microsoft/autogen) - a programming framework for agentic AI
- [anything-llm](https://github.com/Mintplex-Labs/anything-llm) - the all-in-one Desktop & Docker AI application with built-in RAG, AI agents, No-code agent builder, MCP compatibility, and more
- [Flowise](https://github.com/FlowiseAI/Flowise) - build AI agents, visually
- [llama_index](https://github.com/run-llama/llama_index) - the leading framework for building LLM-powered agents over your data
- [crewAI](https://github.com/crewAIInc/crewAI) - a framework for orchestrating role-playing, autonomous AI agents
- [agno](https://github.com/agno-agi/agno) - a full-stack framework for building Multi-Agent Systems with memory, knowledge and reasoning
- [sim](https://github.com/simstudioai/sim) - open-source platform to build and deploy AI agent workflows
- [openai-agents-python](https://github.com/openai/openai-agents-python) - a lightweight, powerful framework for multi-agent workflows
- [SuperAGI](https://github.com/TransformerOptimus/SuperAGI) - an open-source framework to build, manage and run useful Autonomous AI Agents
- [camel](https://github.com/camel-ai/camel) - the first and the best multi-agent framework
- [pydantic-ai](https://github.com/pydantic/pydantic-ai) - a Python agent framework designed to help you quickly, confidently, and painlessly build production grade applications and workflows with Generative AI
- [txtai](https://github.com/neuml/txtai) - all-in-one open-source AI framework for semantic search, LLM orchestration and language model workflows
- [agent-framework](https://github.com/microsoft/agent-framework) - a framework for building, orchestrating and deploying AI agents and multi-agent workflows with support for Python and .NET
- [archgw](https://github.com/katanemo/archgw) - a high-performance proxy server that handles the low-level work in building agents: like applying guardrails, routing prompts to the right agent, and unifying access to LLMs, etc.
- [ClaraVerse](https://github.com/badboysm890/ClaraVerse) - privacy-first, fully local AI workspace with Ollama LLM chat, tool calling, agent builder, Stable Diffusion, and embedded n8n-style automation
- [ragbits](https://github.com/deepsense-ai/ragbits) - building blocks for rapid development of GenAI applications

[Back to Table of Contents](#table-of-contents)

### Model Context Protocol

- [mindsdb](https://github.com/mindsdb/mindsdb) - federated query engine for AI - the only MCP Server you'll ever need
- [github-mcp-server](https://github.com/github/github-mcp-server) - GitHub's official MCP Server
- [playwright-mcp](https://github.com/microsoft/playwright-mcp) - Playwright MCP server
- [chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp) - Chrome DevTools for coding agents
- [n8n-mcp](https://github.com/czlonkowski/n8n-mcp) - a MCP for Claude Desktop / Claude Code / Windsurf / Cursor to build n8n workflows for you
- [awslabs/mcp](https://github.com/awslabs/mcp) - AWS MCP Servers — helping you get the most out of AWS, wherever you use MCP
- [mcp-atlassian](https://github.com/sooperset/mcp-atlassian) - MCP server for Atlassian tools (Confluence, Jira)

[Back to Table of Contents](#table-of-contents)

### Retrieval-Augmented Generation

- [pathway](https://github.com/pathwaycom/pathway) - Python ETL framework for stream processing, real-time analytics, LLM pipelines and RAG
- [graphrag](https://github.com/microsoft/graphrag) - a modular graph-based RAG system
- [LightRAG](https://github.com/HKUDS/LightRAG) - simple and fast RAG
- [haystack](https://github.com/deepset-ai/haystack) - AI orchestration framework to build customizable, production-ready LLM applications, best suited for building RAG, question answering, semantic search or conversational agent chatbots
- [vanna](https://github.com/vanna-ai/vanna) - an open-source Python RAG framework for SQL generation and related functionality
- [graphiti](https://github.com/getzep/graphiti) - build real-time knowledge graphs for AI Agents
- [onyx](https://github.com/onyx-dot-app/onyx) - the AI platform connected to your company's docs, apps, and people
- [claude-context](https://github.com/zilliztech/claude-context) - make entire codebase the context for any coding agent
- [pipeshub-ai](https://github.com/pipeshub-ai/pipeshub-ai) - a fully extensible and explainable workplace AI platform for enterprise search and workflow automation

[Back to Table of Contents](#table-of-contents)

### Coding Agents

- [zed](https://github.com/zed-industries/zed) - a next-generation code editor designed for high-performance collaboration with humans and AI
- [OpenHands](https://github.com/All-Hands-AI/OpenHands) - a platform for software development agents powered by AI
- [cline](https://github.com/cline/cline) - autonomous coding agent right in your IDE, capable of creating/editing files, executing commands, using the browser, and more with your permission every step of the way
- [aider](https://github.com/Aider-AI/aider) - AI pair programming in your terminal
- [opencode](https://github.com/sst/opencode) - a AI coding agent built for the terminal
- [tabby](https://github.com/TabbyML/tabby) -  an open-source GitHub Copilot alternative, set up your own LLM-powered code completion server
- [continue](https://github.com/continuedev/continue) - create, share, and use custom AI code assistants with our open-source IDE extensions and hub of models, rules, prompts, docs, and other building blocks
- [void](https://github.com/voideditor/void) - an open-source Cursor alternative, use AI agents on your codebase, checkpoint and visualize changes, and bring any model or host locally
- [goose](https://github.com/block/goose) - an open-source, extensible AI agent that goes beyond code suggestions
- [Roo-Code](https://github.com/RooCodeInc/Roo-Code) - a whole dev team of AI agents in your code editor
- [crush](https://github.com/charmbracelet/crush) - the glamourous AI coding agent for your favourite terminal
- [kilocode](https://github.com/Kilo-Org/kilocode) - open source AI coding assistant for planning, building, and fixing code
- [humanlayer](https://github.com/humanlayer/humanlayer) - the best way to get AI coding agents to solve hard problems in complex codebases
- [ProxyAI](https://github.com/carlrobertoh/ProxyAI) - the leading open-source AI copilot for JetBrains

[Back to Table of Contents](#table-of-contents)

### Computer Use

- [open-interpreter](https://github.com/OpenInterpreter/open-interpreter) - a natural language interface for computers
- [OmniParser](https://github.com/microsoft/OmniParser) - a simple screen parsing tool towards pure vision based GUI agent
- [cua](https://github.com/trycua/cua) - the Docker Container for Computer-Use AI Agents
- [self-operating-computer](https://github.com/OthersideAI/self-operating-computer) - a framework to enable multimodal models to operate a computer
- [Agent-S](https://github.com/simular-ai/Agent-S) - an open agentic framework that uses computers like a human
- [openwork](https://github.com/different-ai/openwork) - an open-source alternative to Claude Cowork, powered by OpenCode

[Back to Table of Contents](#table-of-contents)

### Browser Automation

- [puppeteer](https://github.com/puppeteer/puppeteer) - a JavaScript API for Chrome and Firefox
- [playwright](https://github.com/microsoft/playwright) - a framework for Web Testing and Automation
- [browser-use](https://github.com/browser-use/browser-use) - make websites accessible for AI agents
- [firecrawl](https://github.com/mendableai/firecrawl) - turn entire websites into LLM-ready markdown or structured data
- [stagehand](https://github.com/browserbase/stagehand) -  the AI Browser Automation Framework
- [nanobrowser](https://github.com/nanobrowser/nanobrowser) -  open-source Chrome extension for AI-powered web automation

[Back to Table of Contents](#table-of-contents)

### Memory Management

- [mem0](https://github.com/mem0ai/mem0) - universal memory layer for AI Agents
- [letta](https://github.com/letta-ai/letta) - the stateful agents framework with memory, reasoning, and context management
- [supermemory](https://github.com/supermemoryai/supermemory) - memory engine and app that is extremely fast, scalable
- [cognee](https://github.com/topoteretes/cognee) - memory for AI Agents in 5 lines of code
- [LMCache](https://github.com/LMCache/LMCache) - supercharge your LLM with the fastest KV Cache Layer
- [memU](https://github.com/NevaMind-AI/memU) - an open-source memory framework for AI companions

[Back to Table of Contents](#table-of-contents)

### Testing, Evaluation, and Observability

- [langfuse](https://github.com/langfuse/langfuse) - an open-source LLM engineering platform: LLM Observability, metrics, evals, prompt management, playground, datasets. Integrates with OpenTelemetry, Langchain, OpenAI SDK, LiteLLM, and more
- [opik](https://github.com/comet-ml/opik) - debug, evaluate, and monitor your LLM applications, RAG systems, and agentic workflows with comprehensive tracing, automated evaluations, and production-ready dashboards
- [openllmetry](https://github.com/traceloop/openllmetry) - an open-source observability for your LLM application, based on OpenTelemetry
- [garak](https://github.com/NVIDIA/garak) - the LLM vulnerability scanner from NVIDIA
- [giskard](https://github.com/Giskard-AI/giskard) - an open-source evaluation & testing for AI & LLM systems
- [agenta](https://github.com/Agenta-AI/agenta) - an open-source LLMOps platform: prompt playground, prompt management, LLM evaluation, and LLM observability all in one place

[Back to Table of Contents](#table-of-contents)

### Research

- [Perplexica](https://github.com/ItzCrazyKns/Perplexica) -  an open-source alternative to Perplexity AI, the AI-powered search engine
- [gpt-researcher](https://github.com/assafelovic/gpt-researcher) - an LLM based autonomous agent that conducts deep local and web research on any topic and generates a long report with citations
- [SurfSense](https://github.com/MODSetter/SurfSense) - an open-source alternative to NotebookLM / Perplexity / Glean
- [open-notebook](https://github.com/lfnovo/open-notebook) - an open-source implementation of Notebook LM with more flexibility and features
- [RD-Agent](https://github.com/microsoft/RD-Agent) - automate the most critical and valuable aspects of the industrial R&D process
- [local-deep-researcher](https://github.com/langchain-ai/local-deep-researcher) - fully local web research and report writing assistant
- [local-deep-research](https://github.com/LearningCircuit/local-deep-research) - an AI-powered research assistant for deep, iterative research
- [maestro](https://github.com/murtaza-nasir/maestro) - an AI-powered research application designed to streamline complex research tasks

[Back to Table of Contents](#table-of-contents)

### Training and Fine-tuning

- [OpenRLHF](https://github.com/OpenRLHF/OpenRLHF) - an easy-to-use, high-performance open-source RLHF framework built on Ray, vLLM, ZeRO-3 and HuggingFace Transformers, designed to make RLHF training simple and accessible
- [Kiln](https://github.com/kiln-ai/kiln) - the easiest tool for fine-tuning LLM models, synthetic data generation, and collaborating on datasets
- [augmentoolkit](https://github.com/e-p-armstrong/augmentoolkit) - train an open-source LLM on new facts

[Back to Table of Contents](#table-of-contents)

### Miscellaneous

- [context7](https://github.com/upstash/context7) - up-to-date code documentation for LLMs and AI code editors
- [deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open) - open source DeepWiki: AI-powered wiki generator for GitHub/Gitlab/Bitbucket repositories
- [cai](https://github.com/aliasrobotics/cai) - Cybersecurity AI (CAI), the framework for AI Security
- [speakr](https://github.com/murtaza-nasir/speakr) - a personal, self-hosted web application designed for transcribing audio recordings
- [presenton](https://github.com/presenton/presenton) - an open-source AI presentation generator and API
- [OmniGen2](https://github.com/VectorSpaceLab/OmniGen2) - exploration to advanced multimodal generation
- [4o-ghibli-at-home](https://github.com/TheAhmadOsman/4o-ghibli-at-home) - a powerful, self-hosted AI photo stylizer built for performance and privacy
- [Observer](https://github.com/Roy3838/Observer) - local open-source micro-agents that observe, log and react, all while keeping your data private and secure
- [mobile-use](https://github.com/minitap-ai/mobile-use) - a powerful, open-source AI agent that controls your Android or IOS device using natural language
- [gabber](https://github.com/gabber-dev/gabber) - build AI applications that can see, hear, and speak using your screens, microphones, and cameras as inputs
- [promptcat](https://github.com/sevenreasons/promptcat) - a zero-dependency prompt manager/catalog/library in a single HTML file

[Back to Table of Contents](#table-of-contents)

## Hardware

- [Alex Ziskind](https://www.youtube.com/@AZisk) - tests of pcs, laptops, gpus etc. capable of running LLMs
- [Digital Spaceport](https://www.youtube.com/@DigitalSpaceport) - reviews of various builds designed for LLM inference
- [JetsonHacks](https://www.youtube.com/@JetsonHacks) - information about developing on NVIDIA Jetson Development Kits
- [Miyconst](https://www.youtube.com/@Miyconst) - tests of various types of hardware capable of running LLMs
- [Kolosal - LLM Memory calculator](https://www.kolosal.ai/memory-calculator) - estimate the RAM requirements of any GGUF model instantly
- [LLM Inference VRAM & GPU Requirement Calculator](https://app.linpp2009.com/en/llm-gpu-memory-calculator) - calculate how many GPUs you need to deploy LLMs
- [ZLUDA](https://github.com/vosen/ZLUDA) - CUDA on non-NVIDIA GPUs

[Back to Table of Contents](#table-of-contents)

## Tutorials

### Models

- [Let's reproduce GPT-2 (124M)](https://www.youtube.com/watch?v=l8pRSuU81PU)
- [nanochat](https://github.com/karpathy/nanochat) - a full-stack implementation of an LLM like ChatGPT in a single, clean, minimal, hackable, dependency-lite codebase, designed to run on a single 8XH100 node via scripts like speedrun.sh, that run the entire pipeline start to end
- [Knowledge Distillation: How LLMs train each other](https://www.youtube.com/watch?v=jrJKRYAdh7I)
- [gguf-docs](https://github.com/iuliaturc/gguf-docs) - Docs for GGUF quantization (unofficial)

[Back to Table of Contents](#table-of-contents)

### Prompt Engineering

- [Prompt Engineering Guide](https://github.com/dair-ai/Prompt-Engineering-Guide) - guides, papers, lecture, notebooks and resources for prompt engineering
- [Prompt Engineering by NirDiamant](https://github.com/NirDiamant/Prompt_Engineering) - a comprehensive collection of tutorials and implementations for Prompt Engineering techniques, ranging from fundamental concepts to advanced strategies
- [Prompting guide 101](https://services.google.com/fh/files/misc/gemini-for-google-workspace-prompting-guide-101.pdf) - a quick-start handbook for effective prompts by Google
- [Prompt Engineering by Google](https://drive.google.com/file/d/1AbaBYbEa_EbPelsT40-vj64L-2IwUJHy/view) - prompt engineering by Google
- [Prompt Engineering by Anthropic](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview) - prompt engineering by Anthropic
- [Prompt Engineering Interactive Tutorial](https://github.com/anthropics/courses/blob/master/prompt_engineering_interactive_tutorial/README.md) - Prompt Engineering Interactive Tutorial by Anthropic
- [Real world prompting](https://github.com/anthropics/courses/blob/master/real_world_prompting/README.md) - real world prompting tutorial by Anthropic
- [Prompt evaluations](https://github.com/anthropics/courses/blob/master/prompt_evaluations/README.md) - prompt evaluations course by Anthropic
- [system-prompts-and-models-of-ai-tools](https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools) - a collection of system prompts extracted from AI tools
- [system_prompts_leaks](https://github.com/asgeirtj/system_prompts_leaks) - a collection of extracted System Prompts from popular chatbots like ChatGPT, Claude & Gemini
- [Prompt from Codex](https://github.com/openai/codex/blob/main/codex-rs/core/prompt.md) - Prompt used to steer behavior of OpenAI's Codex

[Back to Table of Contents](#table-of-contents)

### Context Engineering

- [Context-Engineering](https://github.com/davidkimai/Context-Engineering) - a frontier, first-principles handbook inspired by Karpathy and 3Blue1Brown for moving beyond prompt engineering to the wider discipline of context design, orchestration, and optimization
- [Awesome-Context-Engineering](https://github.com/Meirtz/Awesome-Context-Engineering) - a comprehensive survey on Context Engineering: from prompt engineering to production-grade AI systems

[Back to Table of Contents](#table-of-contents)

### Inference

- [vLLM Production Stack](https://github.com/vllm-project/production-stack) - vLLM's reference system for K8S-native cluster-wide deployment with community-driven performance optimization

[Back to Table of Contents](#table-of-contents)

### Agents

- [GenAI Agents](https://github.com/NirDiamant/GenAI_Agents) - tutorials and implementations for various Generative AI Agent techniques
- [500+ AI Agent Projects](https://github.com/ashishpatel26/500-AI-Agents-Projects) - a curated collection of AI agent use cases across various industries
- [12-Factor Agents](https://github.com/humanlayer/12-factor-agents) - principles for building reliable LLM applications
- [Agents towards production](https://github.com/NirDiamant/agents-towards-production) - end-to-end, code-first tutorials covering every layer of production-grade GenAI agents, guiding you from spark to scale with proven patterns and reusable blueprints for real-world launches
- [Agent Skills](https://github.com/agentskills/agentskills) - a simple, open format for giving agents new capabilities and expertise
- [LLM Agents & Ecosystem Handbook](https://github.com/oxbshw/LLM-Agents-Ecosystem-Handbook) - one-stop handbook for building, deploying, and understanding LLM agents with 60+ skeletons, tutorials, ecosystem guides, and evaluation tools
- [601 real-world gen AI use cases](https://cloud.google.com/transform/101-real-world-generative-ai-use-cases-from-industry-leaders) - 601 real-world gen AI use cases from the world's leading organizations by Google
- [A practical guide to building agents](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf) - a practical guide to building agents by OpenAI

[Back to Table of Contents](#table-of-contents)

### Retrieval-Augmented Generation

- [Pathway AI Pipelines](https://github.com/pathwaycom/llm-app) - ready-to-run cloud templates for RAG, AI pipelines, and enterprise search with live data
- [RAG Techniques](https://github.com/NirDiamant/RAG_Techniques) - various advanced techniques for Retrieval-Augmented Generation (RAG) systems
- [Controllable RAG Agent](https://github.com/NirDiamant/Controllable-RAG-Agent) - an advanced Retrieval-Augmented Generation (RAG) solution for complex question answering that uses sophisticated graph based algorithm to handle the tasks
- [LangChain RAG Cookbook](https://github.com/lokeswaran-aj/langchain-rag-cookbook) - a collection of modular RAG techniques, implemented in LangChain + Python

[Back to Table of Contents](#table-of-contents)

### Miscellaneous

- [Self-hosted AI coding that just works](https://www.reddit.com/r/LocalLLaMA/comments/1lt4y1z/selfhosted_ai_coding_that_just_works/)

[Back to Table of Contents](#table-of-contents)

## Communities

- [LocalLLaMA](https://www.reddit.com/r/LocalLLaMA)
- [LLMDevs](https://www.reddit.com/r/LLMDevs)
- [LocalLLM](https://www.reddit.com/r/LocalLLM)
- [LocalAIServers](https://www.reddit.com/r/LocalAIServers/)
- [GenAI monitor](https://t.me/genaimon) - monitoring updates & fresh releases related to LLMs, diffusion models and Generative AI

[Back to Table of Contents](#table-of-contents)

# Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to get started.

---

**Source:** https://github.com/rafska/awesome-local-llm
**Saved:** 2026-01-23
