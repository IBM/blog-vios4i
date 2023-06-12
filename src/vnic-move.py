#!/QOpensys/pkgs/bin/python3

# Changes all vNIC backing devices on a specific VIOS to alternate backing devices to 
# allow VIOS maintenance in a controlled manner.  
#
# Find the current version on Github at https://github.com/IBM/blog-vios4i
# See https://blog.vios4i.com for setup and usage instructions
# Eclipse Public License v2.0
# license: epl-2.0 

import io
import sys
import subprocess
import argparse

description="""Changes vNIC backing devices to alternate devices to allow maintenance on a VIOS server.

This script will access the HMC and system specified to determine which vNIC devices are currently
on the specified vios server and generate the commands to move those vNIC devices to the lowest 
(number) priority backing device that is Operational on a different VIOS server.  If a vNIC does 
not have any operational alternative backing devices it will print an error message.  You should 
really pay attention to that because it means you are going to lose connectivity if you take that
VIOS down for maintenance without first creating a backing device via a different vios.

There is also an offline option for cases where the HMC is not directly accessible to the network
where this command is run.  To use offline mode, first use the --offline option to get the command
to run on the HMC.  Run that commands and save or cut/paste the output to a text file on the computer
where this is run, then re-run this command with the --file option to process the HMC output.  This
will produce the commmands that should be run to switch the backing devices.  

WARNING: in offline mode, be careful that no vNIC changes occur between collection of the --offline
output and when the output is processed to generate the commands.  It would be wise to run it twice 
to verify that all changes are complete.

The --autofailover option can be used to change the autofailover option on all vNIC devices for 
the specified system to either 1 or 0.  After VIOS maintenance is complete, it can be used to 
reset all vNIC devices to the proper backing devices based on priority.
"""

parser = argparse.ArgumentParser(description=description)

inputgroup = parser.add_mutually_exclusive_group(required=True)
inputgroup.add_argument("--hmc",help="HMC to connect to for vNIC information [username@]hmcname - user portion defaults to hscroot")
inputgroup.add_argument("--file",help="Filename containing HMC command output (for use wihout connection to HMC)")
inputgroup.add_argument("--offline",help="Show the command to get HMC data for offline use",action="store_true")

reqdgroup = parser.add_mutually_exclusive_group(required=True)
reqdgroup.add_argument("--vios",help="VIOS to disable backing devices")
reqdgroup.add_argument("--autofailover",help="Set autofailover flag on all vNICs",choices=['0','1'])

parser.add_argument("--system",help="System name for vNICs to process",required=True)
parser.add_argument("--verify",help="Check for errors and print commands but do not run",action="store_true")
parser.add_argument("--force",help="Run generated commands even if errors are found",action="store_true")

args = parser.parse_args()

if (args.file!=None and args.hmc!=None):
  parser.error("--hmc and --file are mutually exclusive")

if (args.hmc == None):
  if (args.force):
    parser.error("--force is only valid with --hmc")

if (args.file != None):
  if (args.file == '-'):
    hmcORfile=sys.stdin
  else:
    hmcORfile=open(args.file,"r")
else:
  hmcORfile = args.hmc
  if not '@' in hmcORfile:
    hmcORfile = 'hscroot@' + hmcORfile
  
if (args.offline):
  hmcORfile = "%%OFFLINE"


sysname = args.system
if (sysname == None): 
  sysname="SYSTEM" 
  
viosdown = args.vios # VIOS to be cleared of VNICs

# Code from here on:

def run_hmc_query(hmc, basecmd, namelist):
  """Runs a query command on HMC and parses output
  
  Runs a query command on the specified HMC and parses the output into an array of hashes
   that map field names to field values - one array element per line - like a database
   query function.

 Parameters are passed by position AND keyword hash reference
   1 (required)  :  The hmc host name where the command to collect the data offline
                     or '%%OFFLINE' to print the command to run on HMC offline
                     or a file or stream (like sys.stdio) containing the command output 
   2 (required)  :  The base comand to be run.  Usually 'lssyscfg' with some options.
   3 (required)  :  a reference to an Array of field names to retreive.

 Returns a list of disctionaries of field names to field contents.  One element per line returned
  by the HMC command.

 Example call:
      alllpars = run_on_hmc(hmc,
                            "lssyscfg -r lpar -m sysname ",
                             ['name',lpar_id','lpar_env','curr_profile','state']
                             );
"""

  command = basecmd + ' --header -F ' + '%'.join(namelist);
  readdata=''
  
  if (hmc=="%%OFFLINE"):
    print("Collect data from HMC with the following command and store in a file:")
    print(command)
    return []
    
  
  # special case of open file passed for HMC, which allows that file to be substituted for HMC call to allow offline testing
  if (isinstance(hmc,io.IOBase)):
    readdata = hmc.read()
  else:
    process = subprocess.run(["ssh",hmc,"-o","BatchMode=yes",command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8", universal_newlines=True) 
    if (process.returncode != 0):
      print("Error processing SSH Command: "+command)
      print(process.stderr)
      return([])
    readdata = process.stdout
    if ("No results were found." in readdata):
      return([])
  
  cmdResp = readdata.split("\n")
  
  hdr = cmdResp.pop(0).split('%')
  
  rtndata = []
  
  for line in cmdResp:
    mydict = dict()
    d=line.split("%")
    if (len(d) == len(hdr)) :
      for i in range(len(d)):
        mydict[hdr[i]]=d[i]
      rtndata.append(mydict)
    
  return rtndata


def structuredfield(data,namelist):
  """extract a list of HMC structured fields
  
  This function extracts a list of dictionaries from an HMC structured field that contains a comma seperated list of slash delimited values.  WARNING: this
  will not handle the crazy quoting on fields like virtual_fc_adapters.
  
  Parameter 1 - the data to be parsed
  Paramater 2 - An ordered list of the field names for the slash delimited values for each list item
  
  Example Call: backingstate = structuredfield(vnic['backing_device_states'],['sriov','sriov-logical-port-ID','active','status'])
  
  Example of  the format processed:
    sriov/2701c001/1/Operational,sriov/27018001/0/Operational,sriov/27018002/0/NotOperational
    
  Example of output from that data:
    [{'sriov': 'sriov', 'sriov-logical-port-ID': '2701c001', 'active': '1', 'status': 'Operational'}, {'sriov': 'sriov', 'sriov-logical-port-ID': '27018001', 'active': '0', 'status': 'Operational'}, {'sriov': 'sriov', 'sriov-logical-port-ID': '27018002', 'active': '0', 'status': 'NotOperational'}]
    
  """
  
  rtndata=[]
  
  for group in data.split(','):
    mydict = dict()
    d = group.split('/')
    for i in range(max(len(d),len(namelist))):
      mydict[namelist[i]]=d[i]
    rtndata.append(mydict)
    
  return rtndata
  
  
def byprty(bdev):
  """sort function to allow sorting of backing device dictionaries by failover-priority"""
  
  return bdev['failover-priority']

#
## Start of Mainline
#

errors=0
commands=[]

# these will be parameters
vniclist = run_hmc_query(hmcORfile,f'lshwres -m {sysname} -r virtualio --rsubtype vnic',['lpar_name','lpar_id','slot_num','auto_priority_failover','backing_devices','backing_device_states'])

if (hmcORfile=="%%OFFLINE"):
  exit(0)


viosfound=False

for vnic in vniclist:
  if (viosdown != None):
    # this part is for vios disable processing 
    changeit = False
    newbdev = None
    backinglist = structuredfield(vnic['backing_devices'],['sriov','vios-lpar-name','vios-lpar-ID','sriov-adapter-ID','sriov-physical-port-ID','sriov-logical-port-ID',
    'current-capacity','desired-capacity','failover-priority','current-max-capacity','desired-max-capacity'])
    backingstate = structuredfield(vnic['backing_device_states'],['sriov','sriov-logical-port-ID','active','status'])
  
    # make a lookup table by sriov-logical-port-id
    statlookup = dict()
    for bstate in backingstate:
      statlookup[bstate['sriov-logical-port-ID']]=bstate
  
    for bdev in sorted(backinglist,key=byprty):
      bstate = statlookup[bdev['sriov-logical-port-ID']]
      bdev['state']=bstate
      if (bdev['vios-lpar-name'] == viosdown):
        viosfound=True
        if (bstate['active']=='1'):
          changeit = True
      else:
        if (bstate['status'] == 'Operational'):
          if (newbdev == None):
            # only the first one
            newbdev = bdev
      if (bstate['active']=='1'):
        origbdev = bdev
    
    if (changeit):
      if (newbdev == None):
        print("ERROR: No operational backup device found to replace active device on "+viosdown+" for Lpar "+vnic['lpar_id']+" slot "+vnic['slot_num'])
        errors+=1
      else:
        cmd = "chhwres -m "+sysname+" -r virtualio --rsubtype vnicbkdev -o act --id "+vnic['lpar_id']+" -s "+vnic['slot_num']+" --logport "+newbdev['sriov-logical-port-ID']
        commands.append(cmd)
        print("Changing Lpar "+vnic['lpar_name']+" slot "+vnic['slot_num']+" to device with priority "+newbdev['failover-priority']+" because it IS running on vios "+viosdown)
    else:
      print("NOT Changing Lpar "+vnic['lpar_name']+" slot "+vnic['slot_num']+" because it is running on vios "+origbdev['vios-lpar-name'])

  elif (args.autofailover != None):
    # this part is for autofailover processing
    viosfound = True # This just keeps the vios not found from triggering
    if (args.autofailover != vnic['auto_priority_failover']):
      cmd = "chhwres -m "+sysname+" -r virtualio --rsubtype vnic -o s --id "+vnic['lpar_id']+" -s "+vnic['slot_num']+" -a \"auto_priority_failover="+str(args.autofailover)+'"'
      commands.append(cmd)
      print("Changing Lpar "+vnic['lpar_name']+" slot "+vnic['slot_num']+" to auto_priority_failover="+str(args.autofailover))

if (not viosfound):
  print("ERROR: vios "+viosdown+" was not found in any vNIC record - verify parameters are correct, especially vios name")
  errors+=1

if (args.file != None or args.verify):
  print("\nCommands to change vNIC Backing devices are:")
  for cmd in commands:
    print(cmd)
  
if (errors>0):
  print("ERROR: "+str(errors)+" errors found")
  
if (args.verify or args.file != None):
  exit(0)

if (errors>0):
  if (args.force):
    print("hold onto your butts - --force specified, so we're doing this even with the errors")
  else:
    print("Skipping execution of commands - use --force if you know what you are doing and want to bypass errors")
    exit(0)


print("Running commands to change vNIC")

for cmd in commands:
  print("running: "+cmd)
  process = subprocess.run(["ssh",hmcORfile,"-o","BatchMode=yes",cmd],stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8", universal_newlines=True) 
  if (process.returncode != 0):
    print("Error processing SSH Command: "+cmd)
    print(process.stderr)
    print(process.stdout)
