"""Fail closed before publishing an initramfs missing encrypted-root support."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
loader=importlib.machinery.SourceFileLoader('makk_boot_check',str(Path(__file__).resolve().parents[1]/'src/makos/libexec/makk-boot-check'))
spec=importlib.util.spec_from_loader(loader.name,loader);check=importlib.util.module_from_spec(spec);loader.exec_module(check)
class BootCheckTests(unittest.TestCase):
 def test_root_dependency_names_come_from_active_mapping(self):
  self.assertEqual(check.encrypted_roots([{'name':'root-lv','type':'lvm','children':[{'name':'cryptroot','type':'crypt','children':[{'name':'disk3','type':'part','uuid':'fixture'}]}]}]),[('cryptroot','fixture')])
 def test_recovery_name_mismatch_and_wrong_uuid_are_rejected(self):
  for text in ('dm_crypt-0 UUID=fixture none luks,initramfs','cryptroot UUID=other none luks,initramfs','cryptroot UUID=fixture none luks','cryptroot UUID=fixture none luks,initramfs,noauto'):
   with self.subTest(text=text),self.assertRaises(RuntimeError):check.check_crypttab(text,[('cryptroot','fixture')])
 def test_complete_unlock_tree_and_missing_components(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for name in ('cryptroot/crypttab','usr/sbin/cryptsetup','usr/lib/cryptsetup/askpass','scripts/local-top/cryptroot','scripts/local-block/cryptroot','usr/sbin/lvm'):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('cryptroot UUID=fixture none luks,initramfs\n' if name=='cryptroot/crypttab' else 'fixture')
   check.check_tree(root,[('cryptroot','fixture')],True)
   (root/'usr/sbin/lvm').unlink()
   with self.assertRaisesRegex(RuntimeError,'lvm'):check.check_tree(root,[('cryptroot','fixture')],True)
   (root/'usr/sbin/lvm').write_text('fixture');(root/'scripts/local-top/cryptroot').unlink()
   with self.assertRaisesRegex(RuntimeError,'local-top/cryptroot'):check.check_tree(root,[('cryptroot','fixture')],True)
