  6. Implement the remaining agents.
     memory.py, boss.py, kengriffin.py, and the LLM trader are done.

  7. Connect all agents to the episode. Done.

  8. Record and replay every model call so an episode can be re-run exactly.
     Put the prompts, responses, model, and sampling settings in the run data.

  9. Build the four detector datasets. Done.
     experiments/dataset.py builds the situation, observable, private-chat and
     private-reasoning blocks for withholding and misreporting, at both a
     same-round and a next-round horizon. experiments/detector.py fits the
     shared logistic regression and scores it. tests/test_dataset.py pins the
     timing rules that keep the act being predicted out of its own features.

  10. Run a small pilot. Done.

  11. Run the full experiment. Done.
      runs/sweep-main: 5 pressure levels x 12 shared seeds x 10 rounds, 60 of
      60 episodes, 1200 trader-rounds. Written up in RESULTS.md.

  Next:

  12. Get more misreporting, or drop it as a target.
      23 positives in 1200 trader-rounds. Every detector above the
      situation-only model scores at or below the base rate. Either the sweep
      needs to be much larger or the design needs to make under-reporting pay
      -- at present a trader gains nothing from it, so there is little to
      predict.

  13. Find out why pressure 1 produces more withholding than pressure 4.
      The step from no pressure to some pressure is significant; the ordering
      above it is not. Worth knowing whether the harsher directives suppress
      the behaviour, or only suppress traders talking about it.

  14. Test on a second model family.
      Every result so far is one model, Llama-3.3-70B-Instruct. The
      attenuating boss in particular may be a property of this model rather
      than of the hierarchy.
