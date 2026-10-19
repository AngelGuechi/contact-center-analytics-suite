import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'02-modern-ai'))
from qa_shared.demo import ensure_sample


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        sample=ensure_sample(Path(self.temp.name)/'Synthetic_sample.ods')
        self.env=patch.dict(os.environ,{'QA_STORE_PATH':str(Path(self.temp.name)/'qa.db'),
            'QA_DATA_DIR':self.temp.name,'QA_SAMPLE_FILE':str(sample),'QA_INPUT_FOLDER':'','OPENAI_API_KEY':''})
        self.env.start()
        self.app=AppTest.from_file(str(ROOT/'02-modern-ai/app.py'),default_timeout=30).run()

    def tearDown(self):self.env.stop();self.temp.cleanup()

    def page(self,name):
        self.app.radio[0].set_value(name).run()
        self.assertFalse(self.app.exception)

    def test_all_pages_open_and_pivots_browse(self):
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[1].value,'714')
        for name in ['Pivot Tables','Markdowns','Agent & coaching','AI assistant','Settings']:self.page(name)
        self.page('Pivot Tables')
        next(s for s in self.app.selectbox if s.label=='Pivot view').set_value('Sampled calls by agent').run()
        self.assertFalse(self.app.exception)
        self.assertEqual(int(self.app.dataframe[0].value.sum().sum()),1512)

    def test_supervisor_filter_updates_totals(self):
        self.app.selectbox(key='filter_supervisor').set_value('Team 1').run()
        self.assertEqual(self.app.metric[1].value,'119')

    def test_no_key_explains_missing_connection(self):
        self.page('AI assistant')
        next(b for b in self.app.button if b.label=='Generate AI draft').click().run()
        self.assertTrue(any('API key' in e.value for e in self.app.error))
        self.assertFalse(self.app.exception)

    def test_settings_survive_navigation(self):
        self.page('Settings')
        self.app.selectbox(key='_model_widget').set_value('gpt-6-luna').run()
        self.page('AI assistant')
        self.assertEqual(self.app.session_state['model'],'gpt-6-luna')

    def test_save_coaching_survives_refresh(self):
        self.page('Agent & coaching')
        self.app.text_area[0].set_value('Review the recorded OIR evidence together.')
        next(b for b in self.app.button if b.label=='Save coaching').click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any('Coaching saved' in s.value for s in self.app.success))
        from storage import Store
        store=Store(Path(self.temp.name)/'qa.db')
        self.assertEqual(len(store.coaching()),1)
        next(b for b in self.app.button if b.label=='Refresh input files').click().run()
        self.assertEqual(len(store.coaching()),1)
        self.assertFalse(self.app.exception)


if __name__=='__main__':unittest.main()
