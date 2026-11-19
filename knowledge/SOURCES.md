# Knowledge base sources

The retriever indexes every `*.md` file in this folder except this one. Each
file is a paraphrased summary with YAML front matter (`id`, `title`, `source`,
`species`, `topics`, and optional `suggested_tasks` / `requires_vet`). To add a
source, drop in a new file with the same front matter. No code changes needed.

| File | Source | Notes |
|------|--------|-------|
| `avma_animal_health_overview.md` | AVMA, "Animal health and welfare" hub page (pasted by project owner) | Principles only: preventive care, VCPR, dental, microchip |
| `pvc_*.md` (8 files) | Premier VetCare, "Pet Care Basics" client brochure (PDF supplied by project owner) | Split by topic so retrieval returns focused chunks |

## Content deliberately excluded (safety filter)

Some passages in the Premier VetCare brochure were left out because an AI
planner repeating them could harm a pet. Some are also out of date compared
with current veterinary guidance:

1. **Drug doses for home use.** The brochure gives syrup of ipecac and hydrogen
   peroxide volumes for inducing vomiting. Current guidance is to induce
   vomiting only when a vet or animal poison control line says to, and ipecac
   is no longer recommended. Replaced with "call your vet / poison control."
2. **Over-the-counter human medicines.** Pepto-Bismol for diarrhea, and
   "enteric-coated" aspirin. Pepto-Bismol contains a salicylate that is
   dangerous for cats, and aspirin dosing needs a vet. Excluded entirely.
3. **Honey/sugar for seizing puppies.** This is a medical intervention. Replaced
   with "keep the pet safe and call the vet."
4. **Brand-name products** (a flea topical and several pet-food brands). The
   planner should not recommend products; the owner's vet chooses them.

These exclusions shape the guardrails in `pawpal_ai/guardrails.py`: proposed
tasks that mention doses, specific drugs, or emergency treatment are blocked
or routed to human review.

## Known gaps

- No source gives **walk or exercise durations** by age, size, or breed. The
  30-minute walk in `pvc_daily_routine.md` is labelled as a PawPal+ default.
- Little **cat-specific** enrichment or feeding-frequency guidance.
- The brochure is a single clinic's handout, not a peer-reviewed reference.
