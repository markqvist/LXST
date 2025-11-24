all: release

clean:
	@echo Cleaning...
	-rm -rf ./build
	-rm -rf ./dist
	-rm -r ./LXST/__pycache__

remove_symlinks:
	@echo Removing symlinks for build...
	-rm ./RNS
	-rm ./LXST/Utilities/LXST
	-rm ./examples/LXST

create_symlinks:
	@echo Creating symlinks...
	-ln -s ../Reticulum/RNS ./
	-ln -s ../../LXST/ ./LXST/Utilities/LXST
	-ln -s ../LXST/ ./examples/LXST

build_wheel:
	cp ./lib/static/* ./LXST/
	touch ./skip_extensions
	python3 setup.py sdist bdist_wheel
	rm ./skip_extensions
	-@(rm ./LXST/*.so)
	-@(rm ./LXST/*.dll)

native_libs:
	./march_build.sh

persist_libs:
	-cp ./lib/dev/*.so ./lib/static/
	-cp ./lib/dev/*.dll ./lib/static/
	-cp ./lib/dev/*.dylib ./lib/static/

release: remove_symlinks build_wheel create_symlinks

upload:
	@echo Ready to publish release, hit enter to continue
	@read VOID
	@echo Uploading to PyPi...
	twine upload dist/*
	@echo Release published
