# Knowledge base sources

The retriever indexes every `*.md` file in this folder except this one. Each
file is a paraphrased summary with YAML front matter (`id`, `title`, `source`,
`species`, `topics`, and optional `suggested_tasks` / `requires_vet`). To add a
source, drop in a new file with the same front matter. No code changes needed.

| File | Source | Notes |
|------|--------|-------|
| `avma_animal_health_overview.md` | AVMA, "Animal health and welfare" hub page (pasted by project owner) | Principles only: preventive care, VCPR, dental, microchip |
| `pvc_*.md` (8 files) | Premier VetCare, "Pet Care Basics" client brochure (PDF supplied by project owner) | Split by topic so retrieval returns focused chunks |
| `akc_dog_exercise.md` | American Kennel Club exercise guidance (updated Aug 2026) | Read in full; puppy/age/breed numbers partly from AKC's companion walking article as shown in search |
| `aspca_cat_care.md` | ASPCA "General Cat Care" + AAHA/AAFP 2021 Feline Life Stage Guidelines | ASPCA read in full; AAHA/AAFP points (box count, enrichment) from search excerpts |
| `merck_puppy_care.md` | Merck Veterinary Manual, "Puppy Care" (reviewed Jul 2025) | Read in full; deworming dosing omitted |
| `cornell_cat_feeding.md` | Cornell Feline Health Center, "How often should you feed your cat?" (2024) | Read in full |
| `aspca_toxic_foods.md` | ASPCA Animal Poison Control, "People Foods to Avoid Feeding Your Pets" | Read in full |
| `vca_dental_care.md` | VCA "Brushing Your Dog's Teeth" (Jun 2023) + AAHA 2019 Dental Guidelines + VOHC | VCA read in full; AAHA/VOHC "daily" from search excerpts |
| `aaha_senior_care.md` | AAHA 2023 Senior Care Guidelines + AVMA senior pets page | Both pages refused or returned nothing to the fetcher; summarized from guideline excerpts in search results, so treat as lower confidence |

The seven web sources above were found and summarized on 2026-11-18. Each file's front matter records its URL and access date.

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

- ~~No source gives walk or exercise durations.~~ Closed: `akc_dog_exercise.md`
  gives durations by age and breed (about 30 minutes for less active breeds, an
  hour or more for high-energy breeds, short sessions for puppies).
- ~~Little cat-specific guidance.~~ Closed: `aspca_cat_care.md` and `cornell_cat_feeding.md`.
- Still missing: species other than dogs and cats, and non-US guidance.
- The brochure is a single clinic's handout, not a peer-reviewed reference. Where it conflicts with the newer sources (for example, exam frequency), the newer sources reflect current guidance.
