# Assumptions and Ambiguities

The PRD intentionally leaves technology and some clinical behavior open. These
assumptions allowed implementation to proceed safely.

1. **Synthetic data only.** No real PHI is entered, stored or transmitted.
2. **Telephony.** The mandatory workflow may use a deterministic call simulator. Daily
   WebRTC is an enhancement; PSTN requires a licensed SIP/phone provider.
3. **EHR.** A validated FHIR-shaped mock adapter is sufficient and replaceable.
4. **Clinical policy.** Protocol red flags override generative output. Uncertainty,
   disagreement and incomplete information escalate.
5. **Consensus.** Two evidence paths plus a highest-severity rule satisfy independent
   assessment.
6. **Identity.** Local signed evaluation tokens provide reviewer access. Optional
   Supabase validation is supported when deployment variables exist.
7. **Queue capacity.** Capacity is per hospital across campaigns. Advisory locks serialize
   tenant capacity accounting while hospitals schedule independently.
8. **Fairness.** Bounded age points prevent indefinite starvation.
9. **Retries.** Three attempts is the prototype default; campaign configuration is the
   intended production source of truth.
10. **Notifications.** Internal dashboard delivery satisfies the required mechanism.
11. **Compliance.** Production-oriented does not mean HIPAA or clinical certification.
12. **Free tier.** The worker runs in the API process because Railway blocks a third
    service; an independent worker image is included.