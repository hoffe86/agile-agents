// Fixture for the S1 collision test. Two AVM module references pinned to old
// versions — the shape a "bump every module" request acts on.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param namePrefix string

module storage 'br/public:avm/res/storage/storage-account:0.9.0' = {
  name: '${namePrefix}-storage'
  params: {
    name: '${namePrefix}sa'
    location: location
    skuName: 'Standard_LRS'
    publicNetworkAccess: 'Disabled'
  }
}

module vault 'br/public:avm/res/key-vault/vault:0.6.1' = {
  name: '${namePrefix}-kv'
  params: {
    name: '${namePrefix}-kv'
    location: location
    enablePurgeProtection: true
  }
}

output storageId string = storage.outputs.resourceId
output vaultId string = vault.outputs.resourceId
