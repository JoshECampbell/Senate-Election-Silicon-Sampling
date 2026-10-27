"""Tests run:
- Check 100-seat totals, fixed seats, independent winners, ties and majority labels.
- Preserve all persona points, response denominators, model shapes and validation categories in SVGs.
- Check Toronto reporting dates, missing days, complete-run selection and historical views without backfilling.
- Verify query usage totals without counting repeated personas as extra requests.
- Hide incomplete automated models while retaining their saved usage and retry costs.
- Check figure caching, repaired outputs and pruning limited to superseded generated figures.

Usage: uv run python -m unittest discover -s test -p 'test_site_preparation.py' -v
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import copy
import json
import tempfile
from unittest.mock import patch

import polars as pl
import yaml
import unittest
import xml.etree.ElementTree as ET

from site_figures import senate_figure, response_figure, state_figure, validation_figure
from site_data import CATEGORIES, project_senate, state_result, reporting_date, choose_candidate, load_history, headline_outcome, request_usage, cumulative_usage
from prepare_website import overview_records, FigureCache, response_inputs, latest_overview_prefix, prune_superseded_figures


class PreparedFigureTests(unittest.TestCase):
    def test_seat_lead_does_not_imply_an_outright_majority(self):
        for d,r,i,label in (
            (50,48,2,'Democrats lead; no outright majority'),
            (45,53,2,'Republican majority'),
            (47,51,2,'Republican majority'),
            (51,47,2,'Democratic majority'),
            (48,50,2,'Republicans lead; no outright majority'),
            (49,49,2,'Parties tied; no outright majority')):
            totals={'democrat':d,'republican':r,'independent':i,'unallocated':0}
            self.assertEqual(headline_outcome(totals)[0],label)
        # Keep the independent segment between parties and remove the misleading
        # cumulative 51-seat tick: at D50/R48 that tick used to sit in red.
        senate={'totals':{'democrat':50,'republican':48,'independent':2,'unallocated':0}}
        content=senate_figure(senate)
        root=ET.fromstring(content)
        bars=[n for n in root.iter() if n.tag.endswith('rect') and n.get('height')=='26.000']
        self.assertEqual([n.get('fill') for n in bars],['#326A9D','#777777','#BD4942'])
        self.assertEqual([float(n.get('width')) for n in bars],[450.,18.,432.])
        self.assertNotIn('51 seats',content)

    def setUp(self):
        self.means = dict(zip([c[0] for c in CATEGORIES], [.44, .42, .04, .10]))
        self.values = {"points": [{"draw": i+1, **self.means} for i in range(100)],
                       "means": self.means, "draws": 100, "valid": 100, "unique": 1,
                       "eligible": True}
        self.models = {"jev": {"label":"Jev","shape":"circle","dash":""},
                       "mercury": {"label":"Mercury","shape":"triangle","dash":"7 4"},
                       "decider": {"label":"Perplexity","shape":"square","dash":"2 4"}}
        self.history = {"dates":["2026-10-26","2026-10-27"],"models":self.models,
                        "states":{"test-state":{"name":"Test State"}},"snapshots":{}}
        for day in self.history["dates"]:
            self.history["snapshots"][day]={"models":{key:{"states":{"test-state":self.values},
                "model_id":key,"model_snapshots":["snapshot"],"collected_at":day+"T14:00:00+00:00"} for key in self.models}}

    def test_all_repeated_draws_and_model_shapes_survive_two_dates(self):
        root=ET.fromstring(response_figure("test-state",self.history,"p_democrat","2026-10-27"))
        dots=[n for n in root.iter() if n.get("class")=="persona-dot"]
        means=[n for n in root.iter() if n.get("class")=="mean-dot"]
        self.assertEqual(len(dots),600)  # 100 draws x 3 models x 2 observed dates.
        self.assertEqual(len(means),6)
        self.assertEqual({n.tag.rsplit('}',1)[-1] for n in dots},{'circle','polygon','rect'})
        # Exact probability .44 maps to y=143.52 for every mark. Only x jitters.
        for n in dots:
            if n.tag.endswith('circle'):self.assertEqual(n.get('cy'),'143.520')
        self.assertEqual(sum(n.tag.endswith('path') for n in root.iter()),3)

    def test_missing_model_day_is_a_gap_not_a_zero_or_line(self):
        self.history['snapshots']['2026-10-27']['models'].pop('mercury')
        root=ET.fromstring(response_figure('test-state',self.history,'p_democrat','2026-10-27'))
        self.assertEqual(sum(n.get('class')=='persona-dot' for n in root.iter()),500)
        self.assertEqual(sum(n.tag.endswith('path') for n in root.iter()),2)
        self.history['dates'].append('2026-10-29')
        self.history['snapshots']['2026-10-29']=copy.deepcopy(self.history['snapshots']['2026-10-27'])
        root=ET.fromstring(response_figure('test-state',self.history,'p_democrat','2026-10-29'))
        self.assertEqual(sum(n.tag.endswith('path') for n in root.iter()),2)  # No bridge across missing Oct 28.

    def test_state_bar_keeps_all_models_and_nonvote_denominator(self):
        records={key:{**self.values,'date':'2026-10-27'} for key in self.models}
        root=ET.fromstring(state_figure('Test State',records,self.models))
        bars=[n for n in root.iter() if n.tag.endswith('rect') and n.get('height')=='16.000']
        self.assertEqual(len(bars),12)
        self.assertAlmostEqual(sum(float(n.get('width')) for n in bars),224*3)
        records.pop('mercury')
        content=state_figure('Test State',records,self.models)
        self.assertIn('Mercury',content)
        self.assertIn('Unavailable',content)

    def test_validation_keeps_zero_and_unknown_categories(self):
        data = {"categories": [
            {"category": "A", "persona_share": 1., "reference_share": .75, "difference_pp": 25.},
            {"category": "No response", "persona_share": 0., "reference_share": 0., "difference_pp": 0.},
            {"category": "Unknown code: 42", "persona_share": 0., "reference_share": .25, "difference_pp": -25.}]}
        content = validation_figure("Test State", "Race", data)
        root = ET.fromstring(content)
        self.assertIn("No response", content)
        self.assertIn("Unknown code: 42", content)
        bars = [n for n in root.iter() if n.tag.endswith("rect") and n.get("height") == "7.000"]
        self.assertEqual(len(bars), 6)

    def test_owner_baseline_produces_full_100_seat_projection(self):
        baseline = {"fixed_seats": {"democrat": 32, "republican": 31, "independent": 2},
                    "chamber_seats": 100, "contested_seats": 35}
        senate = project_senate({"p_democrat": 15, "p_republican": 20}, baseline)
        self.assertEqual(senate["totals"], {"democrat": 47, "republican": 51, "independent": 2, "unallocated": 0})
        root = ET.fromstring(senate_figure(senate))
        bars = [n for n in root.iter() if n.tag.endswith("rect") and n.get("height") == "26.000"]
        self.assertAlmostEqual(sum(float(n.get("width")) for n in bars), 900.)
        self.assertIn("2 independent", root.attrib["aria-label"])
        self.assertEqual({n.get('fill') for n in bars},{'#326A9D','#BD4942','#777777'})
        self.assertEqual(len(bars),3)  # Solid totals, no fixed/projected shading.

    def test_independent_wins_and_ties_remain_separate(self):
        baseline = {"fixed_seats": {"democrat": 32, "republican": 31, "independent": 2},
                    "chamber_seats": 100, "contested_seats": 35}
        senate = project_senate({"p_democrat": 14, "p_republican": 18, "p_third_party": 2, "unallocated": 1}, baseline)
        self.assertEqual(senate["totals"], {"democrat": 46, "republican": 49, "independent": 4, "unallocated": 1})
        self.assertEqual(sum(senate["totals"].values()), 100)

    def test_invalid_baseline_or_contested_count_stops_preparation(self):
        baseline = {"fixed_seats": {"democrat": 32, "republican": 31, "independent": 2},
                    "chamber_seats": 100, "contested_seats": 35}
        for bad in ({**baseline, "fixed_seats": {"democrat": 33, "republican": 31, "independent": 2}},
                    {**baseline, "fixed_seats": {"democrat": True, "republican": 62, "independent": 2}}):
            with self.assertRaises(ValueError):
                project_senate({"p_democrat": 15, "p_republican": 20}, bad)
        with self.assertRaises(ValueError):
            project_senate({"p_democrat": 15, "p_republican": 19}, baseline)


class HistoryTests(unittest.TestCase):
    """Failure fixtures test the policy without touching real runs or calling APIs."""

    def test_running_usage_counts_retries_not_repeated_draws_and_keeps_unknowns(self):
        rows=pl.DataFrame([
            {'state':'Georgia','caseid':1,'status':'ok','input_tokens':10,'cost_usd':.01},
            {'state':'Georgia','caseid':1,'status':'ok','input_tokens':10,'cost_usd':.01},
            {'state':'Georgia','caseid':2,'status':'ok','input_tokens':20,'cost_usd':.02},
            {'state':'Georgia','caseid':3,'status':'not_queried','input_tokens':None,'cost_usd':None}])
        fallback=request_usage([],rows)
        self.assertEqual(fallback['attempts'],2)
        self.assertEqual(fallback['input_tokens'],30)
        self.assertIsNone(fallback['output_tokens'])
        self.assertTrue(fallback['partial'])
        attempts=[
            {'input_tokens':None,'response':{'usage':{'input_tokens':100,'output_tokens':5,'cost':.01}}},
            {'response':{'usage':{'prompt_tokens':120,'completion_tokens':4,'cost':.02}}},
            {'status':'error'}]
        logged=request_usage(attempts,rows)
        self.assertEqual(logged['attempts'],3)
        self.assertEqual(logged['input_tokens'],220)
        self.assertEqual(logged['output_tokens'],9)
        self.assertAlmostEqual(logged['known_cost'],.03)
        self.assertEqual(logged['unknown_costs'],1)
        self.assertEqual(logged['unknown_output_tokens'],1)
        total=cumulative_usage([logged,fallback])
        self.assertEqual(total['attempts'],5)
        self.assertEqual(total['input_tokens'],250)
        self.assertEqual(total['output_tokens'],9)
        self.assertEqual(total['unknown_output_tokens'],3)
        self.assertTrue(total['partial'])

    def test_zero_usage_is_known_and_invalid_usage_is_not_summed(self):
        rows=pl.DataFrame({'state':['Georgia'],'caseid':[1]})
        usage=request_usage([{'response':{'usage':{'input_tokens':0,'output_tokens':0,'cost':0}}}],rows)
        self.assertEqual(usage['input_tokens'],0)
        self.assertEqual(usage['output_tokens'],0)
        self.assertEqual(usage['known_cost'],0)
        bad=request_usage([{'input_tokens':True,'output_tokens':-1,'cost_usd':float('nan')}],rows)
        self.assertIsNone(bad['input_tokens'])
        self.assertIsNone(bad['output_tokens'])
        self.assertIsNone(bad['known_cost'])

    def test_latest_reuses_dated_grid_but_mixed_dates_get_their_own_grid(self):
        values={'eligible':True,'means':{'p_democrat':.5}}
        h={'date':'2026-10-27','models':{'jev':{'label':'Jev'}},
           'latest':{'jev':'2026-10-27'},'states':{'georgia':{'name':'Georgia'}},
           'snapshots':{day:{'models':{'jev':{'states':{'georgia':copy.deepcopy(values)}}}}
                        for day in ('2026-10-26','2026-10-27')}}
        self.assertEqual(latest_overview_prefix(h),'figures/2026-10-27/states')
        h['latest']['jev']='2026-10-26'
        self.assertEqual(latest_overview_prefix(h),'figures/2026-10-27/states-latest')
        with tempfile.TemporaryDirectory() as folder:
            site=Path(folder)
            names=('figures/2026-10-26/responses/georgia-p_democrat.svg',
                   'figures/2026-10-26/responses/author-note.txt',
                   'figures/2026-10-26/states/georgia.svg',
                   'figures/2026-10-26/senate/jev.svg',
                   'figures/2026-10-27/states-latest/georgia.svg',
                   'figures/2026-10-27/responses/georgia-p_democrat.svg')
            for name in names:
                path=site/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('keep or prune')
            prune_superseded_figures(site,h)
            self.assertFalse((site/names[0]).exists())
            for name in names[1:]:
                self.assertTrue((site/name).exists(),name)

    def test_unchanged_figures_are_not_rendered_and_missing_outputs_are_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            site=Path(folder)
            output=site/'figures/2026-10-26/test.svg'
            calls=[]
            def renderer(value):
                calls.append(value)
                return f'<svg><title>{value}</title></svg>'
            cache=FigureCache(site)
            cache.render(output,renderer,'first')
            cache.save()
            stamp=output.stat().st_mtime_ns
            # A new build process reloads the cache and never calls the renderer.
            cache=FigureCache(site)
            cache.render(output,renderer,'first')
            self.assertEqual(calls,['first'])
            self.assertEqual(cache.reused,1)
            self.assertEqual(output.stat().st_mtime_ns,stamp)
            cache.render(output,renderer,'corrected')
            self.assertEqual(calls,['first','corrected'])
            output.unlink()
            cache.render(output,renderer,'corrected')
            self.assertTrue(output.exists())
            self.assertEqual(len(calls),3)
            output.write_text('damaged')
            cache.render(output,renderer,'corrected')
            self.assertIn('<svg>',output.read_text())
            self.assertEqual(len(calls),4)

    def test_new_dates_do_not_invalidate_older_response_inputs(self):
        h={'dates':['2026-10-26'],'models':{'jev':{'label':'Jev'}},
           'states':{'georgia':{'name':'Georgia'}},'snapshots':{
               '2026-10-26':{'models':{'jev':{'model_id':'jev','model_snapshots':['v1'],
               'collected_at':'2026-10-26T14:00:00+00:00','states':{'georgia':{'means':.5}}}}}}}
        before=response_inputs(h,'georgia','2026-10-26')
        h['dates'].append('2026-10-27')
        h['snapshots']['2026-10-27']=copy.deepcopy(h['snapshots']['2026-10-26'])
        self.assertEqual(before,response_inputs(h,'georgia','2026-10-26'))
        newer=copy.deepcopy(response_inputs(h,'georgia','2026-10-27'))
        h['snapshots']['2026-10-26']['models']['jev']['states']['georgia']['means']=.6
        self.assertNotEqual(newer,response_inputs(h,'georgia','2026-10-27'))

    def test_date_prefix_and_toronto_midnight(self):
        # 01:37 UTC on Oct 27 is the Oct 26 reporting day in Toronto.
        timestamps=['2026-10-27T01:37:00+00:00']
        self.assertEqual(reporting_date('oct-26-all-models',timestamps,'America/Toronto'),'2026-10-26')
        self.assertEqual(reporting_date('2026-10-26-models',timestamps,'America/Toronto'),'2026-10-26')
        self.assertIsNone(reporting_date('mercury-100',timestamps,'America/Toronto'))
        with self.assertRaises(ValueError):
            reporting_date('2026-10-27-wrong-day',timestamps,'America/Toronto')

    def test_full_sample_validation_refuses_partial_or_mismatched_means(self):
        means=dict(zip([c[0] for c in CATEGORIES],[.44,.42,.04,.10]))
        rows=[{'persona_row':i,'caseid':i,'status':'ok',**means} for i in range(100)]
        self.assertTrue(state_result(rows,list(range(100)),[means])['eligible'])
        bad=copy.deepcopy(rows)
        bad[1]['status']='refused'
        value=state_result(bad,list(range(100)),[means])
        self.assertFalse(value['eligible'])
        self.assertEqual(value['valid'],99)
        self.assertIsNone(value['means'])  # No partial average masquerades as 100 draws.
        self.assertEqual(value['points'],[])
        self.assertFalse(state_result(rows[:-1],list(range(100)),[means])['eligible'])
        self.assertFalse(state_result(rows,list(reversed(range(100))),[means])['eligible'])
        self.assertFalse(state_result(rows,list(range(100)),[{**means,'p_democrat':.45}])['eligible'])

    def test_duplicate_daily_runs_choose_complete_then_latest_without_pooling(self):
        def candidate(run,complete,hour):
            return {'run':run,'complete':complete,'collected_at':f'2026-10-27T{hour}:00:00+00:00'}
        first=candidate('first',True,'09')
        newer=candidate('newer',True,'10')
        failed=candidate('failed',False,'11')
        self.assertIs(choose_candidate([first,newer,failed]),newer)

    def test_discovery_preserves_two_models_when_third_is_missing_or_failed(self):
        # Exercise the actual directory reader and summary reconciliation with a
        # synthetic two-day, three-model study. Mock only shared CES validation.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'docs').mkdir()
            config=yaml.safe_load((ROOT/'docs/site-config.yml').read_text())
            (root/'docs/site-config.yml').write_text(yaml.safe_dump(config))
            samples={f'State {i:02}':list(range(100)) for i in range(35)}
            states={name.lower().replace(' ','-'):{'name':name,'validation':{}} for name in samples}
            # Create the older folder last: filesystem recency must not win.
            for day in ('2026-10-27','2026-10-26'):
                rows=[]
                for key in config['models']:
                    if key=='mercury' and day.endswith('27'):continue
                    for name in samples:
                        for i in range(100):
                            status='refused' if day.endswith('27') and key=='jev' and name=='State 00' and i==0 else 'ok'
                            rows.append({'model_key':key,'model':key,'model_snapshot':'v1',
                                         **config['condition'],'state':name,'persona_row':i,'caseid':i,
                                         'status':status,'requested_at':day+'T14:00:00+00:00',
                                         'p_democrat':.44,'p_republican':.42,'p_third_party':.04,'p_would_not_vote':.10})
                frame=pl.DataFrame(rows)
                summary=frame.group_by('model_key',*config['condition'],'state').agg(
                    *[pl.col(c[0]).mean().alias(c[0]) for c in CATEGORIES])
                run=root/'data/llm_responses'/f'{day}-models'
                run.mkdir(parents=True)
                frame.write_parquet(run/'results.parquet')
                summary.write_parquet(run/'summary.parquet')
            with patch('site_data.validation_data',return_value=(states,samples,[])):
                h=load_history(root)
            self.assertEqual(h['dates'],['2026-10-26','2026-10-27'])
            self.assertEqual(h['latest'],{'jev':'2026-10-26','mercury':'2026-10-26','decider':'2026-10-27'})
            self.assertEqual(sum(v['eligible'] for v in h['snapshots']['2026-10-27']['models']['jev']['states'].values()),34)
            self.assertTrue(h['snapshots']['2026-10-27']['models']['decider']['complete'])
            historical=overview_records(h,'state-00','2026-10-27')
            self.assertNotIn('mercury',historical)  # Never substitute yesterday into a dated view.
            self.assertFalse(historical['jev']['eligible'])
            latest=overview_records(h,'state-00','latest')
            self.assertEqual(latest['mercury']['date'],'2026-10-26')
            self.assertTrue(latest['jev']['eligible'])
            # A daily failed model can have some individually complete states;
            # hide that whole model-day, but retain its paid-attempt totals.
            run=root/'data/llm_responses/2026-10-27-models'
            (run/'run_metadata.json').write_text(json.dumps(
                {'automation':True,'published_models':['decider']}))
            usage={'attempts':5,'partial':False,'known_cost':.05,'unknown_costs':0,
                   'input_tokens':50,'unknown_input_tokens':0,'output_tokens':10,'unknown_output_tokens':0}
            (run/'usage_summary.json').write_text(json.dumps({'jev':usage}))
            with patch('site_data.validation_data',return_value=(states,samples,[])):
                automated=load_history(root)
            failed=automated['snapshots']['2026-10-27']['models']['jev']
            self.assertFalse(any(s['eligible'] for s in failed['states'].values()))
            self.assertEqual(failed['cost']['output_tokens'],10)


if __name__ == "__main__":
    unittest.main()
