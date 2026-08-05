  The simulator should have simple test traders that intentionally:

  1. Share and report truthfully.
  2. Withhold but report truthfully.
  3. Share but misreport.
  4. Withhold and misreport.

  This is purely to test the simulator. 

  They are TraderPolicy classes now, one file but no LLM. They should cover every label branch so we can trust the
  labels before spending anything on inference.

  After that:

  5. Add the LLM trader interface: a TraderPolicy that calls a model once per
     phase and fills in private_reasoning. We need the ellicit reasoning do complete
     the 4th mode. The engine already records that
     field, but nothing writes to it yet, so every reasoning trace is empty
     until the LLM exists. private_reasoning must be the first field in the
     response so the model writes its reasoning before the decision.
     The other way round it is explaining a choice it already made, which
     predicts nothing and makes model 3 against model 4 meaningless.
     WE STILL NEED TO DECIDE WHICH MODEL TO USE


  6. Record and replay every model call so an episode can be re-run exactly.
     Put the model and sampling settings in metadata.json.
  7. Build the four detector datasets.
  8. Run a small pilot.
  9. Full experiment.
