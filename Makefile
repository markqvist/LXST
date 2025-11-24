all: release

clean:
	@echo Cleaning...
	-sudo rm -rf ./build
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
	cp ./lib/0.4.2/* ./LXST/
	python3 setup.py sdist bdist_wheel
	-(rm ./LXST/*.so)
	-(rm ./LXST/*.dll)
	-(rm ./LXST/*.dylib)

native_libs:
	./march_build.sh

persist_libs:
	-cp ./libs/dev/*.so ./libs/static/
	-cp ./libs/dev/*.dll ./libs/static/
	-cp ./libs/dev/*.dylib ./libs/static/

release: remove_symlinks build_wheel create_symlinks

upload:
	@echo Ready to publish release, hit enter to continue
	@read VOID
	@echo Uploading to PyPi...
	twine upload dist/*
	@echo Release published
