import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

class NodeTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).parents[1]/'custom_nodes/comfyui_vault/__init__.py'
        spec=importlib.util.spec_from_file_location('vault_node_checks',path,submodule_search_locations=[str(path.parent)])
        package=importlib.util.module_from_spec(spec)
        self.modules=patch.dict(sys.modules,{'folder_paths':SimpleNamespace(), 'vault_node_checks':package})
        self.modules.start();self.addCleanup(self.modules.stop)
        spec.loader.exec_module(package)
        self.nodes=sys.modules['vault_node_checks.nodes']

    def test_capture_value_chain_preserves_seed_and_long_prompt(self):
        node=self.nodes.CaptureValue()
        seed=18446744073709551615
        returned,first=node.collect(seed,'seed')
        text='A long prompt\n'*1000
        value,second=node.collect(text,'positive_prompt',first)
        self.assertEqual(returned,seed)
        self.assertEqual(second,{'seed':seed,'positive_prompt':text})
        self.assertEqual(value,text)
        self.assertEqual(first,{'seed':seed})

    def test_capture_value_rejects_invalid_chain_values_and_oversize_metadata(self):
        node=self.nodes.CaptureValue()
        for value in (float('nan'),float('inf'),object()):
            with self.assertRaisesRegex(ValueError,'Capture Value'):
                node.collect(value,'value')
        with self.assertRaises(ValueError):node.collect(1,'seed',{'previous':float('nan')})
        with self.assertRaises(ValueError):node.collect(1,'seed',{'large':'x'*1024**2})
        with self.assertRaises(ValueError):node.collect(1,'seed',[])

    def test_archive_files_invalid_long_paths_fail_as_validation_errors(self):
        with tempfile.TemporaryDirectory() as root:
            folders=SimpleNamespace(get_annotated_filepath=lambda name:str(Path(root)/name),
                get_input_directory=lambda:root,get_output_directory=lambda:root,get_temp_directory=lambda:root)
            with patch.object(self.nodes,'folder_paths',folders), patch.object(self.nodes,'config',return_value={'extra_input_roots':[]}):
                with self.assertRaisesRegex(ValueError,'Файл не найден'):
                    self.nodes.ArchiveFiles().archive('p','a',files='x'*10000,prompt={'1':{}},unique_id='1')
