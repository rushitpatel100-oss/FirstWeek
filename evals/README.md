# Evals

Labelled datasets and the eval runner, starting in M1:

| Eval | Dataset |
| --- | --- |
| Extraction and classification | 100 postings, labels drafted by Claude and checked by a person |
| De-duplication | 50 duplicate and 50 distinct posting pairs |
| Report faithfulness | 50 spot-checked claims |
| Tech Lead catch rate | 20 submissions with planted bugs |
| Judge calibration | 30 submissions scored blind by a person |

Fast evals run in CI; full evals cost API credit and run before each milestone closes.
