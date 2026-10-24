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


Spider Evaluation Results for 60 samples
=========================
Mode:                Single-pass
Retrieval K:         15
Total Samples:       60
Exact Match:         23.33%
Execution Accuracy:  91.67%
Inference failures:  0
Skipped samples:     0
LLM calls:           60


[55/60] FAIL   db=pets_1 | Q: How many dog pets are raised by female students?
         reason: Result mismatch: predicted 1 row(s), gold 1 row(s)
         pred:   SELECT COUNT(T1.PetID) FROM Has_Pet AS T1 JOIN Student AS T2 ON T1.StuID = T2.StuID JOIN Pets AS T3 ON T1.PetID = T3.PetID WHERE T2.Sex = 'Female' AND T3.PetType = 'Dog';

         [581/600] FAIL   db=student_transcripts_tracking | Q: What other details can you tell me about students in reverse
         reason: Result mismatch: predicted 15 row(s), gold 15 row(s)
         pred:   SELECT * FROM Students ORDER BY first_name DESC, last_name DESC;

        