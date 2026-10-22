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

 def test_missing_unlock_support_blocks_activation_before_mutation(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);service=self.fixture(root);original=service.run
   def run(*args):
    if args[0]=='/usr/sbin/makk-boot-check':raise RuntimeError('missing cryptroot')
    return original(*args)
   service.run=run
   with self.assertRaisesRegex(RuntimeError,'missing cryptroot'):service.apply()
   self.assertFalse((root/branding.FILES[0]).exists())
   self.assertFalse((service.state/'pending').exists())
 def test_bad_new_image_restores_validated_previous_image(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);service=self.fixture(root);original=service.run;checks=[]
   def run(*args):
    if args[0]=='/usr/sbin/makk-boot-check':
     checks.append(args)
     if len(checks)==2:raise RuntimeError('new image lacks unlock support')
    return original(*args)
   service.run=run
   with self.assertRaisesRegex(RuntimeError,'new image'):service.apply()
   self.assertEqual((root/'boot/initrd.img-fixture').read_bytes(),b'# original fixture\n')
   self.assertEqual(checks[2][1],'--images')
 def test_stale_recovery_image_is_rejected_before_restore(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);service=self.fixture(root);service.apply();original=service.run
   def run(*args):
    if args[0]=='/usr/sbin/makk-boot-check':raise RuntimeError('stale snapshot lacks cryptroot')
    return original(*args)
   service.run=run
   with self.assertRaisesRegex(RuntimeError,'stale snapshot'):service.revert()
   self.assertEqual((root/'boot/initrd.img-fixture').read_bytes(),b'rebuilt fixture')
   self.assertTrue((service.state/'active').exists())
