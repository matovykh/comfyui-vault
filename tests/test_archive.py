import concurrent.futures
import importlib.util
import io
import json
import math
from pathlib import Path
import shutil
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
import zipfile

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.metadata import describe
from app.store import Store

HELPER = Path(__file__).parents[1] / "custom_nodes/comfyui_vault/capture.py"
spec = importlib.util.spec_from_file_location("vault_capture", HELPER)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def graph():
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a quiet forest", "clip": ["1", 1]}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "reference.png"}},
        "4": {"class_type": "KSampler", "inputs": {"seed": 18446744073709551615, "steps": 24, "cfg": 6.5,
            "sampler_name": "euler", "scheduler": "normal", "positive": ["2", 0], "latent_image": ["3", 0]}},
        "5": {"class_type": "ComfyVaultArchiveImages", "inputs": {"images": ["4", 0], "project": "Обложки", "artifact": "Лес"}},
        "99": {"class_type": "KSampler", "inputs": {"seed": 9999, "steps": 999}},
    }


def payload(capture_id=None, artifact="Лес"):
    return {"schema_version": 1, "capture_id": capture_id or str(uuid.uuid4()), "project": "Обложки",
            "artifact": artifact, "archive_node_id": "5", "prompt": graph(),
            "workflow": {"nodes": [], "links": [], "version": 0.4},
            "files": [{"path": "outputs/test.png", "role": "output", "name": "test.png"},
                      {"path": "inputs/ref.png", "role": "input", "name": "reference.png", "comfy_path": "input/reference.png"}],
            "models": [{"name": "base.safetensors", "category": "checkpoints", "comfy_path": "models/checkpoints/base.safetensors"}],
            "warnings": [], "environment": {"python": "3.12"}}


def bundle(data=None, extra=None):
    data = data or payload()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("capture.json", json.dumps(data))
        for f in data["files"]:
            archive.writestr(f["path"], b"some file bytes\x00")
        for path, content in (extra or {}).items():
            archive.writestr(path, content)
    return buffer.getvalue()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "original"
        self.app = create_app(self.root)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def ingest(self, data=None, raw=None):
        return self.client.post("/api/ingest", content=raw or bundle(data), headers={"Content-Type": "application/zip"})

    def test_capture_metadata_download_and_edit(self):
        result = self.ingest()
        self.assertEqual(result.status_code, 201, result.text)
        body = result.json()
        self.assertEqual(body["number"], 1)
        library = self.client.get("/api/library").json()["projects"]
        self.assertEqual(library[0]["name"], "Обложки")
        self.assertEqual(library[0]["artifacts"][0]["version_count"], 1)
        detail = self.client.get(f"/api/versions/{body['id']}").json()
        self.assertEqual(detail["metadata"]["samplers"][0]["parameters"]["seed"], "18446744073709551615")
        self.assertNotIn("99", detail["metadata"]["used_node_ids"])
        self.assertEqual(detail["metadata"]["prompts"][0]["text"], "a quiet forest")
        self.assertEqual(self.client.get(f"/api/versions/{body['id']}/file", params={"path": "inputs/ref.png"}).content, b"some file bytes\x00")
        self.assertEqual(self.client.patch(f"/api/versions/{body['id']}", json={"note": "Получилось", "favorite": True}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/projects/{body['project_id']}", json={"description": "Задача проекта"}).status_code, 200)
        detail = self.client.get(f"/api/versions/{body['id']}").json()
        self.assertEqual(detail["note"], "Получилось")
        self.assertEqual(detail["favorite"], 1)

    def test_idempotency_and_numbering(self):
        p = payload()
        first = self.ingest(p).json()
        again = self.ingest(p).json()
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(self.ingest().json()["number"], 2)
        self.assertEqual(self.ingest(payload(artifact="Небо")).json()["number"], 1)

    def test_parallel_numbering(self):
        store = self.app.state.store
        paths=[]
        for i in range(8):
            path = Path(self.temp.name) / f"{i}.zip"
            path.write_bytes(bundle())
            paths.append(path)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(store.ingest,paths))
        self.assertEqual(sorted(x["number"] for x in results), list(range(1,9)))
        self.assertEqual(len({x["id"] for x in results}),8)

    def test_move_complete_directory(self):
        result=self.ingest().json()
        self.client.patch(f"/api/projects/{result['project_id']}", json={"description":"Сохранить описание"})
        moved=Path(self.temp.name)/"moved"
        shutil.copytree(self.root,moved)
        with TestClient(create_app(moved)) as client:
            library=client.get("/api/library").json()["projects"]
            self.assertEqual(library[0]["description"],"Сохранить описание")
            self.assertEqual(client.get(f"/api/versions/{result['id']}/file",params={"path":"outputs/test.png"}).status_code,200)
            next_version=client.post("/api/ingest",content=bundle(),headers={"Content-Type":"application/zip"})
            self.assertEqual(next_version.json()["number"],2)

    def test_invalid_archives_leave_no_records_or_files(self):
        attempts=[]
        p=payload();p["files"][0]["path"]="outputs/../../escape.png";attempts.append(bundle(p))
        p=payload();p["files"][0]["path"]="outputs/model.safetensors";attempts.append(bundle(p))
        p=payload();p["files"][0]["sha256"]="bad";attempts.append(bundle(p))
        attempts.extend([bundle(extra={"undeclared.txt":b"no"}),b"not a zip"])
        for raw in attempts:
            result=self.ingest(raw=raw)
            self.assertEqual(result.status_code,422,result.text)
        self.assertEqual(self.client.get('/api/library').json()["projects"],[])
        self.assertEqual(list((self.root/'.incoming').iterdir()),[])

    def test_unknown_files_and_path_traversal_are_blocked(self):
        result=self.ingest().json()
        for path in ['../library.sqlite3','/etc/passwd','outputs/../manifest.json','secret.txt','outputs//test.png']:
            self.assertIn(self.client.get(f"/api/versions/{result['id']}/file",params={"path":path}).status_code,(400,404))

    def test_no_ui_workflow_warns(self):
        p=payload();del p['workflow']
        result=self.ingest(p).json()
        detail=self.client.get(f"/api/versions/{result['id']}").json()
        self.assertTrue(any('Визуальный' in w for w in detail['manifest']['warnings']))
        self.assertNotIn('workflow.json',[f['path'] for f in detail['files']])

    def test_dynamic_values_never_guessed(self):
        g=graph();g['7']={'class_type':'RandomInteger','inputs':{'min':1,'max':999}}
        g['4']['inputs']['seed']=['7',0]
        metadata=describe(g,'5')
        self.assertNotIn('seed',metadata['samplers'][0]['parameters'])
        self.assertTrue(any(x['field']=='seed' for x in metadata['unresolved']))

    def test_advanced_sampler_parameters_are_grouped_per_stage(self):
        g={
            '1':{'class_type':'RandomNoise','inputs':{'noise_seed':12345}},
            '2':{'class_type':'KSamplerSelect','inputs':{'sampler_name':'euler'}},
            '3':{'class_type':'BasicScheduler','inputs':{'steps':28,'scheduler':'simple','denoise':1.0}},
            '4':{'class_type':'SamplerCustomAdvanced','inputs':{'noise':['1',0],'sampler':['2',0],'sigmas':['3',0]}},
            '5':{'class_type':'RandomNoise','inputs':{'noise_seed':67890}},
            '6':{'class_type':'BasicScheduler','inputs':{'steps':8,'scheduler':'normal'}},
            '7':{'class_type':'SamplerCustomAdvanced','inputs':{'noise':['5',0],'sampler':['2',0],'sigmas':['6',0],'latent_image':['4',0]}},
            '8':{'class_type':'ComfyVaultArchiveImages','inputs':{'images':['7',0]}}
        }
        result=describe(g,'8')['samplers']
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['parameters']['noise_seed'],'12345')
        self.assertEqual(result[0]['parameters']['steps'],28)
        self.assertEqual(result[1]['parameters']['noise_seed'],'67890')
        self.assertEqual(result[1]['parameters']['steps'],8)
        self.assertEqual(result[1]['sources']['steps'],['6'])

    def test_model_bytes_never_packaged_and_file_hash_matches(self):
        model=Path(self.temp.name)/'model.safetensors';model.write_bytes(b'model')
        path=Path(self.temp.name)/'capture.zip'
        with self.assertRaises(ValueError):
            capture.build_archive(path,{},[{"source":model,"role":"input"}])
        ref=Path(self.temp.name)/'ref.png';ref.write_bytes(b'original')
        data={}
        capture.build_archive(path,data,[{"source":ref,"role":"input"}])
        self.assertEqual(data['files'][0]['sha256'],capture.sha256(ref))

    def test_capture_uses_correct_model_category_and_scopes_branch(self):
        root=Path(self.temp.name)
        (root/'input').mkdir();(root/'input/reference.png').write_bytes(b'ref')
        (root/'models').mkdir();(root/'models/base.safetensors').write_bytes(b'weights')
        class Folders:
            folder_names_and_paths={'checkpoints':[], 'text_encoders':[]}
            @staticmethod
            def get_full_path(category,name):
                return str(root/'models'/name) if category=='checkpoints' else None
            @staticmethod
            def get_annotated_filepath(name):return str(root/'input'/name)
            @staticmethod
            def get_input_directory():return str(root/'input')
            @staticmethod
            def get_output_directory():return str(root/'output')
            @staticmethod
            def get_temp_directory():return str(root/'temp')
        refs,models,warnings,used=capture.collect(graph(),'5',Folders,{'hash_models':True,'extra_input_roots':[]})
        self.assertEqual(len(refs),1)
        self.assertEqual(models[0]['comfy_path'],'models/checkpoints/base.safetensors')
        self.assertEqual(models[0]['sha256'],capture.sha256(root/'models/base.safetensors'))
        self.assertNotIn('99',used)

    def test_node_package_is_downloadable(self):
        result=self.client.get('/api/node-package')
        self.assertEqual(result.status_code,200)
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            self.assertIn('comfyui_vault/nodes.py',archive.namelist())
            self.assertNotIn('comfyui_vault/comfyui_vault.json',archive.namelist())

    def test_nodes_archive_runtime_nan_through_png_zip_and_ingest(self):
        import numpy as np
        from PIL import Image

        root = Path(self.temp.name)
        for directory in ("input", "output", "temp"):
            (root / directory).mkdir()
        reference = root / "input/reference.png"
        Image.new("RGB", (8, 8), "blue").save(reference)
        folders = SimpleNamespace(
            folder_names_and_paths={},
            get_full_path=lambda category, name: None,
            get_annotated_filepath=lambda name: str(root / "input" / name),
            get_input_directory=lambda: str(root / "input"),
            get_output_directory=lambda: str(root / "output"),
            get_temp_directory=lambda: str(root / "temp"),
        )
        package_spec = importlib.util.spec_from_file_location(
            "vault_test_nodes", HELPER.parent / "__init__.py",
            submodule_search_locations=[str(HELPER.parent)])
        package = importlib.util.module_from_spec(package_spec)

        class Tensor:
            def detach(self): return self
            def cpu(self): return self
            def numpy(self): return np.full((8, 8, 3), 0.5)

        def send_to_api(path, settings):
            result = self.ingest(raw=Path(path).read_bytes())
            self.assertEqual(result.status_code, 201, result.text)
            return result.json()

        with patch.dict(sys.modules, {"folder_paths": folders, "vault_test_nodes": package}):
            package_spec.loader.exec_module(package)
            node_module = sys.modules["vault_test_nodes.nodes"]
            helper = sys.modules["vault_test_nodes.capture"]
            g = graph()
            g["2"]["inputs"]["text"] = "A long multiline prompt\n" * 300
            g["3"]["is_changed"] = ["reference hash"]
            g["5"]["is_changed"] = [node_module.ArchiveImages.IS_CHANGED()]
            g["99"]["is_changed"] = float("nan")
            workflow = {"nodes": [], "links": [], "version": 0.4}
            images = [Tensor()]
            with patch.object(helper, "config", return_value={"hash_models": False,
                              "extra_input_roots": [], "url": "http://127.0.0.1:8088"}), \
                 patch.object(helper, "environment", return_value={"comfyui": {"dirty": False}, "custom_nodes": []}), \
                 patch.object(helper, "send_archive", side_effect=send_to_api):
                for number in (1, 2):
                    result = node_module.ArchiveImages().archive(
                        images, "Обложки", "Лес", prompt=g,
                        extra_pnginfo={"workflow": workflow}, unique_id="5")
                    self.assertIs(result["result"][0], images)
                    version_id = result["result"][1].split("version=")[1]
                    detail = self.client.get(f"/api/versions/{version_id}").json()
                    self.assertEqual(detail["number"], number)
                    for filename in ("prompt.json", "outputs/0001_image_0000.png"):
                        response = self.client.get(f"/api/versions/{version_id}/file", params={"path": filename})
                        self.assertEqual(response.status_code, 200, response.text[:100] if filename.endswith("json") else "PNG")
                        if filename.endswith(".png"):
                            with Image.open(io.BytesIO(response.content)) as image:
                                raw_prompt = image.info["prompt"]
                                self.assertEqual(image.size, (8, 8))
                        else:
                            raw_prompt = response.text
                        saved = json.loads(raw_prompt, parse_constant=lambda v: self.fail(f"Non-JSON constant: {v}"))
                        self.assertEqual(saved["4"]["inputs"]["seed"], 18446744073709551615)
                        self.assertEqual(saved["2"]["inputs"]["text"], g["2"]["inputs"]["text"])
                        self.assertTrue(all("is_changed" not in node for node in saved.values()))
                g["5"]["class_type"] = "ComfyVaultArchiveFiles"
                result = node_module.ArchiveFiles().archive(
                    "Обложки", "Лес", files=str(reference), prompt=g, unique_id="5")
                version_id = result["result"][0].split("version=")[1]
                detail = self.client.get(f"/api/versions/{version_id}").json()
                self.assertEqual(detail["number"], 3)
            self.assertTrue(math.isnan(g["5"]["is_changed"][0]))
            self.assertTrue(math.isnan(g["99"]["is_changed"]))


if __name__=='__main__':
    unittest.main()
