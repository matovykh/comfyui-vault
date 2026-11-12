import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store
from test_archive import bundle, payload


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.app = create_app(self.root / 'repo')
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def post(self, path, data):
        response = self.client.post(path, json=data)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def ingest(self):
        response = self.client.post('/api/ingest', content=bundle(), headers={'Content-Type':'application/zip'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_groups_crud_move_and_delete_preserve_moved_files(self):
        version = self.ingest()
        group = self.post('/api/groups', {'name':'Characters'})['id']
        project = self.post('/api/projects', {'name':'Destination', 'group_id':group})['id']
        artifact = self.post('/api/artifacts', {'name':'Empty', 'project_id':project})['id']
        self.assertEqual(self.client.patch('/api/groups/'+group,json={'name':'Studio'}).status_code,200)
        self.assertEqual(self.client.patch('/api/projects/'+version['project_id'],json={'name':'Renamed', 'group_id':group}).status_code,200)
        self.assertEqual(self.client.patch('/api/artifacts/'+version['artifact_id'],json={'name':'Moved', 'project_id':project}).status_code,200)
        self.assertEqual(self.client.delete('/api/projects/'+version['project_id']).status_code,200)
        response=self.client.get(f"/api/versions/{version['id']}/file", params={'path':'outputs/test.png'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/versions/'+version['id']).json()['project_name'],'Destination')
        directory=self.app.state.store.root/self.app.state.store.version_row(version['id'])['path']
        self.assertEqual(self.client.delete('/api/groups/'+group).status_code,200)
        self.assertEqual(self.client.get('/api/versions/'+version['id']).status_code,404)
        self.assertFalse(directory.exists())
        self.assertEqual(self.client.get('/api/library').json()['projects'],[])

    def test_conflicting_names_and_missing_parents(self):
        self.post('/api/groups',{'name':'A'})
        self.assertEqual(self.client.post('/api/groups',json={'name':'A'}).status_code,409)
        p=self.post('/api/projects',{'name':'A'})['id']
        self.assertEqual(self.client.patch('/api/projects/'+p,json={'group_id':'missing'}).status_code,409)
        self.assertEqual(self.client.patch('/api/projects/'+p,json={'name':'  '}).status_code,422)
        self.assertEqual(self.client.delete('/api/invalid/'+p).status_code,404)

    def test_backup_restore_full_library_and_new_number(self):
        version=self.ingest()
        self.client.patch('/api/versions/'+version['id'],json={'favorite':True,'note':'Keep me'})
        backup=self.root/'backup'
        self.post('/api/repository/backup',{'path':str(backup)})
        self.client.delete('/api/projects/'+version['project_id'])
        self.post('/api/repository/import',{'path':str(backup)})
        detail=self.client.get('/api/versions/'+version['id']).json()
        self.assertEqual(detail['note'],'Keep me')
        self.assertEqual(detail['favorite'],1)
        self.assertEqual(self.ingest()['number'],2)
        self.assertFalse((backup/'.vault-location').exists())
        self.assertEqual(Store(backup).detail(version['id'])['note'],'Keep me')
        self.assertEqual(self.client.post('/api/repository/backup',json={'path':str(backup)}).status_code,409)

    def test_import_invalid_backup_leaves_current_library_untouched(self):
        version=self.ingest()
        backup=self.root/'broken'
        self.post('/api/repository/backup',{'path':str(backup)})
        source=Store(backup)
        target=source.file(version['id'],'outputs/test.png')
        target.unlink()
        response=self.client.post('/api/repository/import',json={'path':str(backup)})
        self.assertGreaterEqual(response.status_code,400)
        self.assertEqual(self.client.get('/api/versions/'+version['id']).status_code,200)

    def test_invalid_repository_directory_is_rejected(self):
        self.assertEqual(self.client.post('/api/settings/repository',json={'path':''}).status_code,422)
        occupied=self.root/'occupied';occupied.mkdir();(occupied/'keep.txt').write_text('keep')
        self.assertEqual(self.client.post('/api/settings/repository',json={'path':str(occupied)}).status_code,422)
        self.assertFalse((occupied/'library.sqlite3').exists())

    def test_switch_persists_across_app_restart(self):
        original=self.ingest()
        target=self.root/'second'
        self.post('/api/settings/repository',{'path':str(target)})
        self.assertEqual(self.client.get('/api/library').json()['projects'],[])
        self.assertEqual(self.client.get('/api/settings').json()['repository'],str(target))
        with TestClient(create_app(self.root/'repo')) as client:
            self.assertEqual(client.get('/api/settings').json()['repository'],str(target))
        self.post('/api/settings/repository',{'path':str(self.root/'repo')})
        self.assertEqual(self.client.get('/api/versions/'+original['id']).status_code,200)
        self.assertEqual(self.client.post('/api/settings/repository',json={'path':str(self.root/'repo/nested')}).status_code,422)

    def test_delete_version_and_empty_repository_repopulation(self):
        version=self.ingest()
        self.assertEqual(self.client.delete('/api/versions/'+version['id']).status_code,200)
        self.assertEqual(self.client.get('/api/artifacts/'+version['artifact_id']+'/versions').json()['versions'],[])
        self.assertEqual(self.ingest()['number'],2)
        groups=self.client.get('/api/library').json()['groups']
        for g in groups:
            self.assertEqual(self.client.delete('/api/groups/'+g['id']).status_code,200)
        self.assertEqual(self.client.get('/api/library').json(),{'projects':[],'groups':[]})
        self.ingest()
        self.assertEqual(len(self.client.get('/api/library').json()['groups']),1)
