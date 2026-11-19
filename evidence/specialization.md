# Specialization: few-shot, style-constrained planner vs. baseline

_Generated 2026-11-18 21:41 by `python -m eval.compare_styles` · model: claude-opus-5-5 · 6 planned scenarios per style_

**Baseline:** the planner's normal system prompt. **Specialized:** the same prompt plus three few-shot example tasks and house-style rules (verb-first task names of 2–5 words with no pet name; one-sentence explanations of at most 18 words that state the source's frequency). See `SPECIALIZED_STYLE` in `pawpal_ai/planner.py`.

| Metric | Baseline | Specialized | Note |
|---|---|---|---|
| Task name length (words, avg) | 4.4 | 3.5 | lower is tighter |
| Task names of 5 words or fewer (%) | 68.7 | 100 | style rule |
| Task names starting with a verb (%) | 62.5 | 96.7 | style rule |
| Task names repeating the pet name (%) | 0 | 0 | lower is better |
| Explanation length (words, avg) | 14.8 | 10.8 | lower is tighter |
| Explanations of 18 words or fewer (%) | 85.8 | 100 | style rule |
| Explanations stating a frequency (%) | 80 | 100 | style rule |
| Tasks kept per scenario (avg) | 4.3 | 4.3 | context |
| Planning rounds (avg) | 1 | 1 | context |
| Tasks blocked by guardrails (avg) | 0 | 0 | should stay 0 |

**Example output** (`dog-basic`, first 4 kept tasks):

Baseline:

```text
Refresh water bowl  ->  The source says to keep fresh water available at all times and change it daily.
Daily walk  ->  The source recommends walking or jogging your dog every day.
Playtime and health check  ->  The source recommends daily play and using that time to watch for signs of illness.
Brush teeth with pet toothpaste  ->  The source recommends daily dental care with pet-specific products, never human toothpaste.
```

Specialized:

```text
Refresh water bowl  ->  Source: keep fresh water available at all times and change it daily.
Walk the dog  ->  Source: walk or jog your dog every day.
Play and watch for illness  ->  Source: play with your dog daily and watch for signs of illness.
Brush teeth with pet toothpaste  ->  Source: use a pet dental product daily, never human toothpaste.
```
