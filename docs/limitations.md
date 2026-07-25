# Limitations

Every number here is reproducible from the repository. Where a metric is below
target it is stated with the target, the sample size, and what I believe the
cause to be.

This document exists because the alternative is worse. A reviewer who finds a
weakness I did not name learns that I either did not look or chose not to say;
either reading costs more than the weakness itself.

Numbers as of the golden run over 22 observable sites. See
[architecture.md](architecture.md) for how the system is put together.

---

## 1. Capability induction essentially fails on the offline tier

**This is the largest weakness in the system, and it is not close.**

| Metric | Result | Target | n |
|---|---:|---:|---:|
| Capability precision* | `0.045` | `≥0.90` | 22 sites |
| Capability recall* | `0.015` | `≥0.70` | 22 sites |

One site in twenty-two produced a capability matching its label. The machinery
around induction is sound — the critic rejects correctly, citations resolve,
schemas validate — but `qwen2.5:7b` cannot reliably induce usable capabilities
once the evidence is messy rather than synthetic.

**What I ruled out.** Early runs showed recall at 0.00 with *zero rejections*,
which is the diagnostic tell: the critic was not rejecting bad candidates,
because there were no candidates at all. That was a schema-compliance failure and
was fixed with schema-constrained decoding. What remains is not a prompt-tuning
problem — it is a capability ceiling on a 7B model.

**What would fix it.** Routing induction to Groq or Gemini, both already wired in
the LiteLLM chain and both free-tier. I did not do this for the published run
because the run would then not be reproducible by someone with no API keys, and
the `$0.00` cost claim is load-bearing for this project. That is a defensible
trade but it is a trade, and this table is what it cost.

---

## 2. The golden labels are model-authored

`seeds/golden/labels.yaml` declares `label_source: model` and `circular: true`.

Three metrics depend on those labels, and all three are named
`judge_labelled_*` in `wasl/eval/metrics.py` so the distinction cannot be lost:
capability precision, capability recall, band accuracy.

**Under this condition they measure agreement with the labelling model, not
correctness.** They are not accuracy figures and should not be quoted as such.

This directly contradicts CLAUDE.md §9, which says labels are filled by the
human, by hand. That rule was overridden deliberately and the override is
recorded rather than hidden. The disclosure is carried in the file, in the metric
names, in the eval output, and here.

The four **gate** metrics do not depend on labels and are unaffected.

---

## 3. Wasl underrates API-first companies by exactly one band

Stripe, Twilio, GitHub and Shopify all scored `Readable` against a labelled
`Agent-Ready`. **Four out of four, same direction, same magnitude** — which makes
it diagnostic rather than noise.

The cause: Axis 3 probes `/openapi.json` and `/swagger.json`. All four publish
their specs on GitHub or a developer subdomain, so the check finds nothing and
the axis under-awards by roughly one band's worth of points.

I predicted this in the labels before the run and the data confirmed it. The fix
is a spec-discovery step that follows developer-documentation links rather than
probing two fixed paths. It is not built.

This is also why **band accuracy is 0.556 exact but 1.000 within one band** (18
sites). Never wrong by more than one band is a very different failure shape from
randomly wrong, and the aggregate alone would hide that.

---

## 4. Latency misses its target

`103.3s` p95 against a `≤90s` target, interactive budget.

Two contributors. The floor is arithmetic: 12 pages at 0.5 req/s is 24 seconds of
pure throttle before anything is rendered or reasoned about, and the probe set
adds more. On top of that, the demo node's claim-verification pass added model
calls that were not in the original budget.

The throttle is not negotiable — it is the politeness guarantee, and raising it
to hit a latency target would be exactly the wrong trade. Realistic improvements
are caching the probe set and running the demo asynchronously after the report is
delivered.

---

## 5. Score stability is measured against fixtures

`0.0` max delta across repeated runs — but scoring is a deterministic function
over evidence, so against a fixed fixture the only honest expectation *is* zero.
This metric mostly proves the deterministic-core claim rather than measuring
real-world variance.

The variance that would matter comes from crawl non-determinism: which pages get
discovered, whether hydration completed, whether a site A/B-tests its markup.
Measuring that requires repeated live crawls of the same sites, which costs real
requests to third parties. I have not run it.

---

## 6. "Required property" is our operational definition

Axis 2 awards points for JSON-LD validating "with zero required-property
violations". schema.org has no formal notion of required properties — only
`domainIncludes`/`rangeIncludes` and Google's per-rich-result requirements.

`wasl/scoring/schema_required.yaml` is a versioned table derived from Google's
rich-results documentation. It is **our operational definition**, not a standard,
and a site could disagree with it in good faith.

One deliberate omission worth naming: it does not require `postalCode`, because
that would penalise correctly-formatted UAE addresses, which frequently have
none. That is a judgement call baked into a scoring table, which is exactly the
kind of thing that should be visible rather than buried.

---

## 7. What is planned and not built

- **Batch crawl and the public leaderboard.** `GET /api/leaderboard` returns 501.
  `Budget.BATCH` is defined and has no caller; the `LeaderboardEntry` table is
  never populated. The frontend route is an honest empty shell that refuses to
  render placeholder scores.
- **CI.** There is no `.github` directory. `wasl.eval.run` exits non-zero on gate
  failure and is ready to be a CI gate, but nothing runs it automatically. The
  gates are real; the automation is not.
- **Adversarial fixture corpus.** 11 hand-labelled injection payloads exist
  against a planned 20–30, and the planned hard negatives — a site with an `/api`
  marketing page but no real API — are not built. Injection recall of 1.000 is
  therefore measured on a set small enough that one miss would move it to 0.909.
- **The backend is not deployed.** The public site is frontend-only and says so
  on the scan page rather than failing on click. Scanning runs locally.

---

## 8. Coverage and sample size

The golden set is 30 sites, of which **22 are observable**; 8 are robots-blocked
or unreachable and carry null bands. Band accuracy is computed over 18, because
four of the 22 scored `SUPPRESSED` — Wasl declined to emit a band on thin
evidence, so there was nothing to compare.

That is the confidence-suppression rule working as designed, but it means the
band figure excludes the cases where the system was least certain. A denominator
that quietly drops the hard cases flatters the metric, so: 18 of 30.

30 is the practical floor for a portfolio project and it is a floor, not a
comfortable sample. Confidence intervals at this size are wider than several of
the differences discussed above.

All 22 observable sites are UAE or global commercial sites. There is no coverage
of government portals in the scored set, which is a gap given the policy framing
around agent-readiness in the public sector.

---

## 9. Generated artifacts are illustrative and unsigned

The MCP server, A2A Agent Card and `llms.txt` that Wasl emits describe a business
that has not published them and has not agreed to them. They carry no signature
and no provenance a third party could verify.

`gate_pregenerate` exists for this reason, and the acknowledgement is required
before anything is written for a domain the submitter has not claimed. The tools
emitted are read/search only — a state-changing capability is reported as
detected and never emitted.

The generated server reads from the cached crawl snapshot by default. Running it
against a live site is opt-in, and doing so at volume would put load on a site
that never asked for any of this.

---

## 10. Known-weaker areas I would probe first

If I were reviewing this system rather than writing it, these are where I would
look:

- **Axis 3 is 25 points and depends most on the weakest signal.** Spec discovery
  is two hardcoded paths (§3). It is the highest-weighted axis and the most
  brittle check in the rubric.
- **Injection recall is measured on 11 payloads.** Convincing at 100+; at 11 it
  is an encouraging signal, not a claim.
- **The demo A/B is honest but single-task.** Both arms are recorded verbatim and
  the UI shows whatever happened, including the raw arm succeeding — but one
  fixed task is one data point, not a comparison.
- **`verify_claims()` in the demo node** was added after the model hallucinated
  product details for a fixture that contained none. It does token-level matching
  against the source, which catches fabrication but would not catch a plausible
  misreading of text that is genuinely present.
