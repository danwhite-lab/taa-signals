import {afterEach,expect,it,vi} from 'vitest';
import text from '../content/compare.json';
const mock=vi.hoisted(()=>({response:vi.fn()}));
vi.mock('../lib/api',()=>({authorizedResponse:mock.response,ApiError:class extends Error {status=0;}}));
import {compareRequest} from '../lib/compareApi';
afterEach(()=>mock.response.mockReset());
it.each([400,403,422,500])('shows the server detail for rejection %s',async status=>{
  mock.response.mockResolvedValue(new Response(JSON.stringify({detail:'Specific comparison validation reason'}),{status}));
  await expect(compareRequest('/api/compare')).rejects.toThrow('Specific comparison validation reason');
});
it('uses validation messages without reflecting submitted values, and masks non-JSON proxy pages',async()=>{
  mock.response.mockResolvedValueOnce(new Response(JSON.stringify({detail:[{msg:'Initial investment must be positive',input:'private-value'}]}),{status:422}));
  await expect(compareRequest('/api/compare')).rejects.toThrow('Initial investment must be positive');
  mock.response.mockResolvedValueOnce(new Response('raw proxy HTML',{status:502}));
  await expect(compareRequest('/api/compare')).rejects.toThrow(text.requestError);
});
