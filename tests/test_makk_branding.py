"""Login/boot activation rollback restores actual bytes, including a failed rebuild."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('makk_branding',str(ROOT/'src/makos/libexec/makk-branding'))
spec=importlib.util.spec_from_loader(loader.name,loader);branding=importlib.util.module_from_spec(spec);loader.exec_module(branding)
class RecoveryTests(unittest.TestCase):
 def fixture(self,root,fail=False):
  for name in ('usr/share/sddm/themes/makk/Main.qml','usr/share/plymouth/themes/makk/makk.plymouth','usr/share/plymouth/themes/makk/watermark.png','boot/initrd.img-fixture','boot/grub/grub.cfg','etc/plymouth/plymouthd.conf'):
   p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'# original fixture\n')
  def run(*args):
   if args[:2]==('update-alternatives','--query'):return 'Status: manual\nValue: /old.plymouth\n'
   if args[0]=='update-initramfs':
    (root/'boot/initrd.img-fixture').write_bytes(b'rebuilt fixture')
    if fail:raise RuntimeError('simulated rebuild failure')
   return ''
  return branding.Branding(root,run)
 def test_apply_and_revert_preserve_original_and_remove_only_owned_overrides(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);service=self.fixture(root);before=(root/'boot/initrd.img-fixture').read_bytes()
   service.apply();self.assertIn('Current=makk',(root/branding.FILES[0]).read_text())
   service.revert();self.assertEqual((root/'boot/initrd.img-fixture').read_bytes(),before)
   self.assertFalse((root/branding.FILES[0]).exists());self.assertFalse((root/branding.FILES[2]).exists())
   self.assertEqual((root/'etc/plymouth/plymouthd.conf').read_bytes(),b'# original fixture\n')
 def test_failed_rebuild_restores_boot_bytes_and_configuration(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);service=self.fixture(root,True)
   with self.assertRaises(RuntimeError):service.apply()
   self.assertEqual((root/'boot/initrd.img-fixture').read_bytes(),b'# original fixture\n')
   self.assertFalse((service.state/'active').exists());self.assertFalse((service.state/'pending').exists())
