#! /bin/bash

set -o errexit
set -o nounset
set -o pipefail

main(){
	IMAGE=baseline
	read -p "Enter docker image [default: $IMAGE]: " IMAGE
	export IMAGE

	IDENTIFIER=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 13; echo)
	read -p "Enter identifier [default: $IDENTIFIER]: " IDENTIFIER
	export IDENTIFIER

	docker run --it --restart always --cpu 1 --memory 500m --label is_racer=y --network racecourse --network-alias "player_${IDENTIFIER}.internal" --name "player_$IDENTIFIER" "$IMAGE"
}
(main)
