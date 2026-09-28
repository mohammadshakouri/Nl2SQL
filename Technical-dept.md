1-n_results in _predict_sql which is number of retrieval unit should be the args of cli_spider_eval.py as --k 15.
2-user_semantic_feedback does not have meaning in spider evaluation and it is related to previous chatbot project.
3- remove culture parameter. all samples and datasets are english.
4-question: isn't necessary to give db_id in addithin of sql query in _execute_sql functions? how it know the db_id which it wants to run given sql?

5- some samples get failed in terminal:
FAIL
which is caused from this block:
if not pred_sql:
            total += 1
            if verbose:
                print(
                    f"[{idx+1}/{len(eval_samples)}] FAIL  db={db_id} "
                    f"| inference returned nothing"
                )
            continue
but i cannot see why they are geting fails. no reason is showing and i cannot figure out the real reason.

6- here is the result of executing with and without feedback loop. it seems that feedback mechanism is working wrong or it has not any affect on result. please make a deep Reviewing in the feedback loop process and diagnostic it.
Spider Evaluation Results for 550 samples:
=========================
Mode:                Single-pass
Total Samples:       550
Exact Match:         18.73%
Execution Accuracy:  72.73%

Spider Evaluation Results for 550 samples with feedback loop.
=========================
Mode:                Feedback loop
Total Samples:       550
Exact Match:         18.73%
Execution Accuracy:  72.55%