.PHONY: ci images-push

ci:
	./ci.sh

images-push:
	./build-and-push-images.sh
