"""Local single-server preview; frontend must be built first."""
import argparse,uvicorn
parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8000);parser.add_argument('--strictPort',action='store_true');args=parser.parse_args()
uvicorn.run('backend.main:app',host=args.host,port=args.port)
