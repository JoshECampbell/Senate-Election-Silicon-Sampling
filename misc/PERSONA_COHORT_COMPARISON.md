# Persona cohort comparison

## Rationale for using 100 personas per state

We selected 100 persona draws per state because this cohort size produced the
closest average agreement with the weighted CES reference among the three
sizes evaluated. Across the six characteristics displayed on the website
(race/ethnicity, gender, education, marital status, voter registration, and
seven-category party identification), mean TVD across 35 states decreased
from 0.128 for 25 draws to 0.089 for 50 draws and 0.066 for 100 draws.
Using unrounded values, the 100-draw cohort reduced average TVD by 48.3%
relative to 25 draws and 26.0% relative to 50 draws. It also had lower TVD
in 166 of 210 state-by-characteristic comparisons against 25 draws (79.0%)
and 144 against 50 draws (68.6%). This provides empirical support for using
100 draws to reduce discrepancies in the composition of the sampled personas.

The same pattern holds across all ten non-state persona characteristics,
including those omitted from the website: mean TVD was 0.151, 0.107, and
0.075 for 25, 50, and 100 draws, respectively. The justification therefore
does not depend on displaying only the six selected characteristics.
These comparisons support 100 as the best-performing size evaluated on
average; they do not establish that 100 is an optimal sample size or guarantee
accurate electoral predictions. Each comparison uses one saved cohort per size.

| Website characteristics: mean TVD across 35 states | 25 Cohort | 50 Cohort | 100 Cohort |
| --- | ---: | ---: | ---: |
| Six displayed characteristics | 0.128 | 0.089 | 0.066 |

## Text for the methods section

We assessed the marginal distributions of the 25-, 50-, and 100-draw persona
cohorts within each of the 35 study states. Validation covered all 11 persona
characteristics: race or ethnicity, gender, state of residence, education,
religious affiliation, marital status, sexual orientation, voter registration,
family income, seven-category party identification, and political ideology.
For each state and characteristic, CES reference proportions were calculated
as the sum of Common Content survey weights within each category divided by
the total survey weight within the state. Persona proportions were calculated
from unweighted draw frequencies because selection probabilities already
incorporated the survey weights. Repeated respondents counted once per draw.
Null, skipped, and not-asked responses were retained in a combined no-response
category; uncertainty and refusal categories remained separate. Agreement was
summarized using total variation distance (TVD), defined as half the sum of
absolute differences between persona and reference category proportions.
TVD ranges from 0 to 1, with lower values indicating closer agreement.
State of residence was retained for completeness but had TVD zero by
construction because sampling was restricted to respondents within each state.

## Full validation results retained for reference

These results use the existing saved cohorts (seed 42); respondents were not
resampled for this comparison. Each size has one cohort per state, with 385
state-by-characteristic comparisons (35 states times 11 characteristics).
Means give each state and characteristic equal weight; they are not national
population-weighted estimates. Values below are rounded to three decimals.

| Characteristic (mean across 35 states) | 25 Cohort | 50 Cohort | 100 Cohort |
| --- | ---: | ---: | ---: |
| Race / ethnicity | 0.102 | 0.083 | 0.064 |
| Gender | 0.071 | 0.063 | 0.047 |
| State of residence | 0.000 | 0.000 | 0.000 |
| Education | 0.164 | 0.118 | 0.079 |
| Religious affiliation | 0.195 | 0.126 | 0.094 |
| Marital status | 0.148 | 0.095 | 0.074 |
| Sexual orientation | 0.087 | 0.064 | 0.041 |
| Voter registration | 0.069 | 0.046 | 0.037 |
| Family income | 0.287 | 0.214 | 0.141 |
| Party identification | 0.215 | 0.133 | 0.096 |
| Political ideology | 0.170 | 0.133 | 0.081 |
| **Mean across all 11 characteristics and states** | **0.137** | **0.098** | **0.069** |
| **Mean excluding state of residence** | **0.151** | **0.107** | **0.075** |

### Optional results paragraph

Mean TVD across the 35 states and 11 characteristics decreased from 0.137 for
25 draws to 0.098 for 50 draws and 0.069 for 100 draws. Excluding state of
residence, which matched by construction, the corresponding means were 0.151,
0.107, and 0.075. The 100-draw cohort had lower TVD than the 25-draw cohort in
295 of the 350 non-state comparisons (84.3%), and lower TVD than the 50-draw
cohort in 252 comparisons (72.0%). Family income showed the largest mean TVD
at every cohort size. These findings describe the saved cohorts; agreement
did not improve in every state-by-characteristic comparison. Marginal agreement
with the weighted CES reference does not establish agreement in joint
distributions, state population representativeness, or electoral prediction accuracy.

## Reproduce

Run the three validation commands in `PERSONA_VALIDATION.md`. Results are
stored in `data/persona_validation/sample_{25,50,100}/sample_*_summary.parquet`.
Each row contains one state's TVD for one characteristic. The website table
uses these rows directly, with the state selector shared by the plots.
