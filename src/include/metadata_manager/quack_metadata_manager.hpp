//===----------------------------------------------------------------------===//
//                         DuckDB
//
// metadata_manager/quack_metadata_manager.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "storage/ducklake_metadata_manager.hpp"

#include <mutex>

namespace duckdb {

class QuackMetadataManager : public DuckLakeMetadataManager {
public:
	explicit QuackMetadataManager(DuckLakeTransaction &transaction);

	static unique_ptr<DuckLakeMetadataManager> Create(DuckLakeTransaction &transaction) {
		return make_uniq<QuackMetadataManager>(transaction);
	}

	bool SupportsAppender() const override {
		return false;
	}
	bool DroppedTablesStayReadable() const override {
		return false;
	}
	bool CommitsEachStatement() const override {
		return true;
	}
	void ProbeServerCapabilities() override;
	bool CanSkipSnapshotFetch(const TransactionChangeInformation &changes) const override;
	void FlushChangesServerSide(DuckLakeTransaction &transaction, DuckLakeSnapshot transaction_snapshot,
	                            const TransactionChangeInformation &transaction_changes,
	                            const DuckLakeRetryConfig &retry_config) override;
	using DuckLakeMetadataManager::Query;
	unique_ptr<QueryResult> Execute(DuckLakeSnapshot snapshot, string &query) override;
	unique_ptr<QueryResult> ExecuteInTransaction(string &query) override;
	unique_ptr<QueryResult> Query(string &query) override;
	unique_ptr<QueryResult> AttachMetadata(const string &attach_query) override;
	void ClearCache() override;

	bool MetadataExists() override;
	bool InlinedDeletionTableExists(const string &table_name) override;

protected:
	string MetadataExistsQuery() const override;

private:
	//! The lock that keeps this transaction's metadata statements and their error recovery from interleaving. An
	//! unpooled quack catalog sends the statements of every transaction over one server connection, so that is the
	//! catalog-wide lock. A pooled one pins each transaction to a connection of its own, so only the statements of
	//! this transaction (which can come from several threads) need to be serialized.
	std::recursive_mutex &QueryLock();
	//! Detect whether the metadata catalog pins each transaction to a connection of its own
	void ProbePooledConnection();

	std::recursive_mutex transaction_query_lock;
};

} // namespace duckdb
