<p align="center">
  <img src="assets/banner.svg" alt="pr-reviewer" width="100%">
</p>

<p align="center"><em>A GitHub Action that reviews pull requests and leaves comments on the diff.</em></p>

<p align="center">
  <img alt="Status: in development" src="https://img.shields.io/badge/status-in%20development-8a3a24?style=flat-square">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-1c1a17?style=flat-square">
  <img alt="GitHub Action" src="https://img.shields.io/badge/GitHub%20Action-1c1a17?style=flat-square">
  <img alt="Backends: API or Hugging Face" src="https://img.shields.io/badge/backends-API%20%7C%20Hugging%20Face-1c1a17?style=flat-square">
</p>

---

## Features

Planned for v1. Progress is tracked in the Roadmap below.

- **Inline review comments**: comments land on the exact lines of the diff they refer to.
- **Summary comment**: one comment per pull request with what changed, risks and suggested tests.
- **Configurable rules**: a `.github/pr-reviewer.yml` file sets what to check, what to ignore and how strict to be.
- **Works with ModelShifts/jira-bridge**: link the review to the Jira task the pull request belongs to via [jira-bridge](https://github.com/ModelShifts/jira-bridge).

## Architecture

```mermaid
%%{init: {"theme":"base","flowchart":{"curve":"basis","wrappingWidth":260},"themeVariables":{"fontFamily":"Georgia, Times New Roman, serif","fontSize":"14px","primaryColor":"#f3efe6","primaryTextColor":"#1c1a17","primaryBorderColor":"#1c1a17","lineColor":"#1c1a17","clusterBkg":"#faf7f0","clusterBorder":"#8a3a24","titleColor":"#8a3a24","edgeLabelBackground":"#f3efe6"}}}%%
flowchart TB
  E["pull_request event"]:::ink --> D["Fetch diff<br/>+ changed files"]:::ink
  D --> R["Rules<br/>.github/pr-reviewer.yml"]:::ink
  R --> V["Reviewer<br/>per-hunk prompts"]:::ink
  V --> I["Inline comments"]:::ink
  V --> S["Summary comment"]:::ink
  S -.-> J["ModelShifts/jira-bridge<br/>(optional)"]:::ink
  subgraph BK["Backend · pick one"]
    direction LR
    BKA["<b>(a) Your API key</b><br/>OpenAI-compatible<br/>code model"]:::rust
    BKH["<b>(b) Hugging Face</b><br/>Qwen2.5-Coder-7B-Instruct<br/>HF Inference or self-hosted"]:::rust
  end
  BK -.-> V

  classDef cl fill:#faf7f0,stroke:#8a3a24,stroke-dasharray:4 3,color:#8a3a24;
  classDef ink fill:#f3efe6,stroke:#1c1a17,color:#1c1a17,stroke-width:1px;
  classDef rust fill:#f3efe6,stroke:#8a3a24,color:#8a3a24,stroke-width:1.5px;
```

### Two interchangeable backends

Pick one with `MS_BACKEND` in `.env`. The rest of the pipeline does not change.

| | (a) Bring your own API key | (b) Open-source on Hugging Face |
|---|---|---|
| **What** | Any OpenAI-compatible endpoint | Open models, run locally or via Hugging Face Inference |
| **Set** | `MS_BACKEND=api`, `OPENAI_BASE_URL`, `OPENAI_API_KEY` | `MS_BACKEND=hf`, `HF_MODE=local` or `inference` |
| **Good for** | Fastest start, strongest hosted models | Data stays on your machines, no per-call cost |

**Default open-source models**

| Model | Used for | License |
|---|---|---|
| [`Qwen/Qwen2.5-Coder-7B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct) | diff review and suggestions | Apache-2.0 |

## Quickstart

> **Coming soon.** The commands below show the planned interface.

```yaml
# .github/workflows/review.yml
name: pr-reviewer
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: ModelShifts/pr-reviewer@v0  # coming soon
        with:
          backend: api            # or: hf
          base-url: ${{ vars.LLM_BASE_URL }}
          api-key: ${{ secrets.LLM_API_KEY }}
          model: ${{ vars.LLM_MODEL }}
```

## Roadmap

- [x] Repository scaffold and README
- [ ] Action that reads the pull request diff
- [ ] Inline review comments
- [ ] Summary comment
- [ ] Configurable rules file
- [ ] jira-bridge integration
- [ ] Marketplace listing

## License

[MIT](LICENSE) © Modelshifts Technology Pte. Ltd.

<p align="center"><sub>Part of the <a href="https://modelshifts.com/work">Modelshifts</a> showcase.</sub></p>
