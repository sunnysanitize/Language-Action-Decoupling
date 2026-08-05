Research overview

Thesis

Whether hierarchical rank pressure causes pretrained LLM trading
agents to misreport or withhold information, and whether that
misconduct can be predicted before it happens from their private
reasoning, beyond what is already predictable from their situation.

Ground-truth and reports are how we compare misconduct

1. Misreporting: reported position does not match the execution.
2. Withholding: useful information is not shared when sharing it would
   have improved firm profit, this can be detected with chain of thought.

These will come from the simulator and our evaluation, not an LLM judge. The two
types of misconduct will be analyzed separately.

Early-warning comparisons

1. Situation only (This is how we determine weather situational pressure causes misconduct)
   - pressure level
   - rank
   - budget
   - P&L gap
   - round number
   - previous behavior

2. Observable information
   - situation information
   - ledger information
   - trader reports
   - public chat

3. Observable information plus private trader chat

4. Observable information, private trader chat, and private reasoning

Basically we will run four experiments, 1, 1+2, 1+2+3, 1+2+3+4 

Each information source will be converted into a fixed feature block which is most likely a vector.
The same regularized logistic-regression model will be used for all of the models and vector inputs.

The main comparison is model 3 against model 4. This will test whether private reasoning will help predictions 
beyond everything else

Evaluation:

- AUPRC will be the main metric because misconduct may be rare.

- AUROC, calibration, and recall under a fixed inspection budget will
  also be reported.

- We will divide all our runs, some of it will be used for training, 
  some of them will be used for testing the mode

- This model will be supervised prediction, we will have the model predict 
  first given the private thoughts or whatever and see if the prediction is correct.
  then will predict if it happens in the next round

- To then generalize our model, we will test it on a pressure level or situation it never 
  was trained on to attempt to generalize it.

- Then we can test it on a differernt general family on LLMs if enough progress is made.

question for the detector

Does private reasoning contain information about future misconduct, or
does it only show that the agent is under pressure?

Contributions

1. Organizational hierarchy and rank pressure can produce emergent
   misconduct in LLM agents.
2. Private reasoning may provide an early-warning signal, but its value
   must be measured beyond situational cues and under distribution
   shift.
