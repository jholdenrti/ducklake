cmake_minimum_required(VERSION 3.5)

# Set extension name here
set(TARGET_NAME ducklake)

set(EXTENSION_NAME ${TARGET_NAME}_extension)
set(LOADABLE_EXTENSION_NAME ${TARGET_NAME}_loadable_extension)

project(${TARGET_NAME})
include_directories(src/include)

# Roaring is installed via vcpkg and used for deletion vectors
find_package(roaring CONFIG REQUIRED)
if(TARGET roaring::roaring-headers)
  get_target_property(ROARING_INCLUDE_DIRS roaring::roaring-headers INTERFACE_INCLUDE_DIRECTORIES)
else()
  get_target_property(ROARING_INCLUDE_DIRS roaring::roaring INTERFACE_INCLUDE_DIRECTORIES)
endif()
if(NOT ROARING_INCLUDE_DIRS OR ROARING_INCLUDE_DIRS STREQUAL "ROARING_INCLUDE_DIRS-NOTFOUND")
  set(ROARING_INCLUDE_DIRS "${roaring_DIR}/../../include")
endif()
include_directories(${ROARING_INCLUDE_DIRS})

add_subdirectory(src)
set(EXTENSION_SOURCES ${ALL_OBJECT_FILES})

build_static_extension(${TARGET_NAME} ${EXTENSION_SOURCES})
build_loadable_extension(${TARGET_NAME} " " ${EXTENSION_SOURCES})

if(TARGET roaring::roaring-headers)
  target_link_libraries(${EXTENSION_NAME} roaring::roaring roaring::roaring-headers roaring::roaring-headers-cpp)
  target_link_libraries(${TARGET_NAME}_loadable_extension roaring::roaring roaring::roaring-headers roaring::roaring-headers-cpp)
else()
  target_link_libraries(${EXTENSION_NAME} roaring::roaring)
  target_link_libraries(${TARGET_NAME}_loadable_extension roaring::roaring)
endif()

# Force the loadable extension to link the SHARED C++ runtime. Some toolchains
# (observed: gcc 16.1 on Arch-family hosts, whose compiler-private lib dir ships
# only libstdc++.a) resolve the driver's implicit -lstdc++ to the static archive
# when linking a shared object, silently embedding a second C++ EH runtime in
# the extension. Exceptions that cross the host/extension boundary then
# unbalance the per-thread std::uncaught_exceptions() counter of one of the two
# runtimes, and DuckDB consults Exception::UncaughtException() on shutdown paths
# (AttachedDatabase::Close TRY_CHECKPOINT, ~ClientContext): a poisoned thread
# silently skips the close-time WAL checkpoint of attached databases (observed
# as a stranded metadata.duckdb.wal after a clean close in go-duckdb hosts) and
# can skip transaction cleanup. Naming libstdc++.so.6 explicitly restores the
# single shared runtime that hosts (duckdb CLI, go-duckdb) link dynamically.
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  target_link_libraries(${LOADABLE_EXTENSION_NAME} -l:libstdc++.so.6)
endif()

install(
  TARGETS ${EXTENSION_NAME}
  EXPORT "${DUCKDB_EXPORT_SET}"
  LIBRARY DESTINATION "${INSTALL_LIB_DIR}"
  ARCHIVE DESTINATION "${INSTALL_LIB_DIR}")
