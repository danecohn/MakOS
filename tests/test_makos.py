"""MakOS logic/security/packaging boundary regressions."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/makos'))
from makos import search,catalog

class MakOSTests(unittest.TestCase):
    def test_calculator_and_resource_limits(self):
        self.assertEqual(search.calculate('(15 + 5) * 3 / 2'),'30')
        self.assertEqual(search.calculate('-12.5 * 2'),'-25')
        for text in ['__import__("os").system("true")','(1).__class__','2**999999','9**9**9','[1]*100','(1+2j)','True','1/0','1e200']:
            with self.subTest(text=text),self.assertRaises((ValueError,SyntaxError,ZeroDivisionError,OverflowError)):
                search.calculate(text)
    def test_units_and_dimension_mismatch(self):
        self.assertEqual(search.convert('1 mi to km'),'1.609344 km')
        self.assertEqual(search.convert('2 kg to g'),'2000 g')
        self.assertIsNone(search.convert('1 m to kg'))
    def test_curated_catalog_keeps_authorized_apps(self):
        ids=[a.id for a in catalog.APPS]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIn('chatgpt',ids);self.assertIn('claude',ids)
        self.assertNotIn('agent',ids)
        self.assertEqual(catalog.BY_ID['makbox'].name,'MakBox')
        for key in ('studio','render','engine','sprite'):
            self.assertEqual(catalog.BY_ID[key].name,key.title())
        for term in ('Konsole','Ptyxis','Amerika'):
            self.assertFalse(search.applications(term))
    def test_exactly_one_terminal_backend(self):
        chosen=catalog.resolve(catalog.BY_ID['terminal'],lambda exe:exe in ('ptyxis','konsole'))
        self.assertEqual(chosen,['ptyxis','--new-window'])
    def test_document_search_is_local_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            (home/'Documents/.hidden').mkdir(parents=True)
            (home/'Documents/Report.txt').write_text('example')
            (home/'Documents/.hidden/Report-secret.txt').write_text('example')
            (home/'Documents/link').symlink_to(home,target_is_directory=True)
            (home/'Outside').mkdir()
            (home/'Outside/Report.txt').write_text('example')
            self.assertEqual(search.documents('report',home),[home/'Documents/Report.txt'])
            self.assertEqual(search.documents('r',home),[])
    def test_asset_validation_rejects_flat_background_and_clipping(self):
        from PIL import Image,ImageDraw
        spec=importlib.util.spec_from_file_location('ingest_makos',ROOT/'tools/ingest_makos_assets.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        with self.assertRaises(ValueError):mod.validate_icon(Image.new('RGB',(1024,1024)),'bad')
        with self.assertRaises(ValueError):mod.validate_icon(Image.new('RGBA',(1024,1024),'white'),'bad')
        im=Image.new('RGBA',(1024,1024));ImageDraw.Draw(im).rectangle((128,128,896,896),fill='white')
        self.assertEqual(mod.validate_icon(im,'good')['center'],[.5,.5])
    def test_packages_do_not_take_over_existing_sessions(self):
        text=(ROOT/'tools/builders/makos.py').read_text()
        self.assertNotIn('META_DEPENDS',text)
        self.assertNotIn("p.scripts['postinst']",text)
        session=(ROOT/'src/makos/session/makos-session').read_text()
        self.assertIn('makos/compositor',session)
        self.assertNotIn('amerika-first-run',session)
        start=(ROOT/'src/makos/session/session-start').read_text()
        self.assertIn('MAKOS_USER_CONFIG_HOME',start)
        self.assertIn('makos-shell',start)
        self.assertNotIn('systemctl enable',start)

if __name__=='__main__':unittest.main()
