const fs=require('fs'),path=require('path');
const sharp=require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1112-611-0_26.1112.611.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/sharp');
const root=path.resolve(__dirname,'..');
(async()=>{
 for(const name of fs.readdirSync(path.join(root,'plots')).filter(x=>/^0[1-4]_.*\.svg$/.test(x))){
  const output=path.join(root,'plots',name.replace('.svg','.png'));
  await sharp(fs.readFileSync(path.join(root,'plots',name)),{density:96}).png().toFile(output);
  console.log(output);
 }
})();
